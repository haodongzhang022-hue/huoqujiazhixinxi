"""条件触发引擎 (trigger.py) —— 货找货: 生态需求信号 -> 主动匹配 -> 自动决策。

这是比检索更高维度的机制 (用户本地 R6 设计):
  检索 = 人找货: 你描述需求 -> 查储备库 -> 给你结果
  触发 = 货找货: 生态需求信号 -> 引擎主动匹配 -> 自动决策

三级决策:
  AUTO    : 强语义匹配 + 条件全满足 -> 直接调用 (返回可执行方案)
  SUGGEST : 部分满足 -> 返回缺口 (缺什么、怎么补)
  LOG     : 无命中 -> 记录需求进 pending_needs, 新项目入库时自动重匹配

双向生长回路:
  未满足需求进 pending_needs -> 新项目入库时自动重匹配 (rematch) -> 需求被满足

CLI 用法:
  python -m reserve.trigger "需要 RAG 向量检索能力" --top 3
  python -m reserve.trigger "MCP agent 智能体工具" --auto
  python -m reserve.trigger --rematch            # 全量重匹配 pending_needs
  python -m reserve.trigger --needs              # 查看 pending_needs
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone

from reserve.store import ReserveStore
from reserve.embedding import embed_text
from reserve.classifier import eco_match_score, load_rules
from reserve.search import search


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def need_id(text: str) -> str:
    return f"need-{uuid.uuid5(uuid.NAMESPACE_URL, text.strip().lower())}"


def trigger(text: str, top_k: int = 5, auto_threshold: float = 0.72,
            suggest_threshold: float = 0.42, store: ReserveStore | None = None,
            decision_filter: str | None = None) -> dict:
    """触发决策: 对一条需求描述给出 AUTO / SUGGEST / LOG。

    匹配分 = 混合检索相似度 (向量 + FTS) + 关键词辅助评分 融合生态匹配度。
    关键词辅助: 中文需求中的英文关键词 (如 mcp/rag/quantum) 直接与仓库文本比对,
    弥补本地 TF 哈希嵌入跨语言 (中文需求 -> 英文仓库) 匹配不足。
    """
    store = store or ReserveStore()
    rules = load_rules()

    # 混合检索
    candidates = search(text, top_k=max(top_k, 10), mode="hybrid", store=store,
                        decision=decision_filter)

    need_tokens = _simple_tokens(text)
    # 中文需求里提取英文关键词 (跨语言桥接)
    en_keywords = [t for t in need_tokens if re.match(r"^[a-z][a-z0-9-]*$", t)]
    # 中英别名扩展 token (含中文术语 -> 英文同义词)
    from reserve.embedding import tokenize as embed_tokenize
    alias_tokens = set(t for t in embed_tokenize(text) if re.match(r"^[a-z][a-z0-9-]*$", t))

    scored = []
    for r in candidates:
        # 相似度: _distance 越小越相似 (向量距离) + FTS _score
        dist = float(r.get("_distance", 1.0) or 1.0)
        vec_sim = 1.0 / (1.0 + dist)
        fts_score = float(r.get("_score", 0.0) or 0.0)
        fts_sim = 1.0 / (1.0 + fts_score) if fts_score > 0 else 0.0
        sim = max(vec_sim, fts_sim)
        # 关键词辅助: 英文关键词命中仓库文本
        kw_hit = 0.0
        alias_hit = 0.0
        if en_keywords:
            repo_text = _repo_text(r)
            hits = sum(1 for k in en_keywords if k in repo_text)
            kw_hit = min(1.0, hits / max(1, len(en_keywords)))
        # 别名 token 命中率 (中文需求 -> 英文仓库的关键桥接)
        if alias_tokens:
            repo_text = _repo_text(r)
            alias_hits = sum(1 for t in alias_tokens if t in repo_text)
            alias_hit = min(1.0, alias_hits / max(1, len(alias_tokens)))
        kw_score = max(kw_hit, alias_hit)
        if kw_score > 0 and sim < 0.5:
            sim = max(sim, 0.35 + 0.15 * kw_score)  # 有真实关键词命中, 抬升基础分
        eco = eco_match_score(r, rules)
        score = round(0.6 * sim + 0.2 * kw_score + 0.2 * eco, 3)
        scored.append({"repo": r, "score": score, "sim": round(sim, 3),
                       "eco": eco, "kw_hit": round(kw_score, 3)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    best = scored[0] if scored else None

    if best and best["score"] >= auto_threshold:
        decision = {
            "level": "AUTO",
            "decision": "直接调用",
            "need": text,
            "score": best["score"],
            "repo": best["repo"],
            "action": _build_action_plan(best["repo"]),
        }
    elif best and best["score"] >= suggest_threshold:
        decision = {
            "level": "SUGGEST",
            "decision": "部分满足",
            "need": text,
            "score": best["score"],
            "repo": best["repo"],
            "gaps": _build_gaps(text, best["repo"]),
        }
    else:
        decision = {
            "level": "LOG",
            "decision": "无命中, 记录需求",
            "need": text,
            "score": best["score"] if best else 0.0,
            "top_candidates": scored[:3] if scored else [],
        }
        # 记录进 pending_needs (双向生长回路)
        _log_need(store, text, decision)

    return decision


def _build_action_plan(repo: dict) -> dict:
    return {
        "action": "clone_and_evaluate",
        "repo_url": repo.get("url"),
        "full_name": repo.get("full_name"),
        "function_tags": repo.get("function_tags"),
        "use_case": repo.get("use_case"),
        "suggested_steps": [
            "clone 仓库并检查 README/许可证",
            f"验证是否满足需求: {repo.get('function_summary', '')}",
            "若匹配, 接入生态/注册到生态目录",
        ],
    }


def _build_gaps(text: str, repo: dict) -> dict:
    """SUGGEST 缺口分析: 需求关键词 vs 仓库能力。"""
    need_tokens = set(_simple_tokens(text))
    topics = repo.get("topics")
    topics = topics if topics is not None else []
    tags = repo.get("function_tags")
    tags = tags if tags is not None else []
    repo_text = " ".join(filter(None, [
        repo.get("name", ""), repo.get("description", ""),
        " ".join([str(t) for t in topics]),
        " ".join([str(t) for t in tags]),
    ])).lower()
    missing = [t for t in need_tokens if t and t not in repo_text]
    return {
        "matched_repo": repo.get("full_name"),
        "score": repo.get("_score"),
        "missing_keywords": missing[:10],
        "advice": f"该仓库覆盖部分需求, 缺失: {', '.join(missing[:5]) or '无明显缺失(建议人工复核)'}",
    }


def _repo_text(repo: dict) -> str:
    """仓库可检索文本 (用于关键词辅助匹配)。"""
    topics = repo.get("topics")
    topics = topics if topics is not None else []
    tags = repo.get("function_tags")
    tags = tags if tags is not None else []
    return " ".join(filter(None, [
        repo.get("name", ""), repo.get("full_name", ""),
        repo.get("description", "") or "",
        repo.get("function_summary", "") or "",
        " ".join([str(t) for t in topics]),
        " ".join([str(t) for t in tags]),
    ])).lower()


def _simple_tokens(text: str) -> list[str]:
    import re as _re
    return _re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())


def _log_need(store: ReserveStore, text: str, decision: dict) -> None:
    needs = store.needs_get()
    nid = need_id(text)
    if any(n.get("id") == nid for n in needs):
        return
    needs.append({
        "id": nid,
        "text": text,
        "keywords": _simple_tokens(text)[:20],
        "status": "open",
        "decision": "LOG",
        "matched_repos": [],
        "created_at": _now(),
    })
    store.needs_put(needs)
    print(f"[trigger] logged pending need: {nid}")


# ============================================================
# 双向生长回路: 新项目入库后自动重匹配 pending_needs
# ============================================================

def rematch_pending_needs(store: ReserveStore | None = None,
                          decision_filter: str | None = None) -> list[dict]:
    """对 pending_needs 全量重匹配 (新项目入库后调用)。

    返回: [{"need": {...}, "matched": repo, "score": s, "level": "AUTO"/"SUGGEST"}]
    """
    store = store or ReserveStore()
    needs = store.needs_get()
    results = []
    for n in needs:
        if n.get("status") == "matched":
            continue
        res = trigger(n["text"], top_k=5, store=store, decision_filter=decision_filter)
        if res["level"] in ("AUTO", "SUGGEST"):
            results.append({
                "need": n,
                "matched": res.get("repo") or res.get("top_candidates", [{}])[0],
                "score": res["score"],
                "level": res["level"],
            })
            # 回写 need
            n["status"] = "matched"
            n["decision"] = res["level"]
            matched_repos = [m.get("full_name") for m in n.get("matched_repos", [])]
            repo_fn = res.get("repo", {}).get("full_name")
            if repo_fn and repo_fn not in matched_repos:
                n["matched_repos"] = n.get("matched_repos", []) + [
                    {"full_name": repo_fn, "score": res["score"]}]
            n["updated_at"] = _now()
    store.needs_put(needs)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="条件触发引擎")
    parser.add_argument("query", nargs="?", help="需求描述")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--decision", choices=["action", "reserve", "partial", "ignore"], default=None)
    parser.add_argument("--rematch", action="store_true", help="重匹配 pending_needs")
    parser.add_argument("--needs", action="store_true", help="查看 pending_needs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    store = ReserveStore()

    if args.needs:
        needs = store.needs_get()
        out = needs
    elif args.rematch:
        out = rematch_pending_needs(store, args.decision)
    elif args.query:
        out = trigger(args.query, top_k=args.top, store=store, decision_filter=args.decision)
    else:
        parser.print_help()
        return 1

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=_json_default))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _json_default(o):
    """numpy 数组/标量 -> 原生类型 (JSON 安全序列化)。"""
    import numpy as np
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())
