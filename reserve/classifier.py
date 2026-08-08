"""条件判断分类器 (classifier.py) —— 打分模型 -> 三分类 + 功能索引生成。

对齐调研报告 §5.3 条件判断机制 (分级打分 + 规则路由 + LLM 复核):

  三级决策:
    action  (生态升级): score >= ACTION_THRESHOLD 且生态匹配 >= ECO_MATCH_THRESHOLD
    reserve (储备索引): score >= RESERVE_THRESHOLD
    partial (部分采用): 命中生态关键词但增长信号不足 (用户本地三分类含 partial)
    ignore  (忽略)    : 信号不足

功能索引 (LLM 或启发式):
  function_tags      功能标签 (如 ["RAG","MCP","vector-db"])
  function_summary   一句话: 它解决什么问题
  use_case           适用场景
  ecosystem_fit      与生态匹配度分析

打分规则 (调研报告 §5.3):
  增长信号:  stars_delta_24h>=500 -> +3 ; stars_delta_7d>=2000 -> +3
            is_new_this_week -> +1 ; stars>=10000 -> +1
  生态匹配:  命中生态关键词 -> +2
  质量信号:  license 明确 && pushed 30 天内 -> +1 ; 未 archived -> +1
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ============================================================
# 可配置规则 (config/reserve_rules.json 热更新)
# ============================================================

DEFAULT_RULES = {
    "thresholds": {
        "action": 7,
        "reserve": 4,
        "eco_match": 0.5,
    },
    "weights": {
        "delta_24h_burst": 3,     # stars_delta_24h >= 500
        "delta_7d_burst": 3,      # stars_delta_7d >= 2000
        "new_this_week": 1,
        "stable_high_stars": 1,   # stars >= 10000
        "eco_match": 2,
        "quality_active": 1,      # license 明确 + pushed 30d 内
        "quality_not_archived": 1,
    },
    "delta_thresholds": {
        "delta_24h_burst": 500,
        "delta_7d_burst": 2000,
        "stable_stars": 10000,
        "active_pushed_days": 30,
    },
    "ecosystem_keywords": [
        "mcp", "model-context-protocol", "agent", "llm", "rag", "vector",
        "knowledge", "embedding", "retrieval", "prompt", "ai", "langchain",
        "langgraph", "crewai", "autogen", "orchestrator", "workflow",
        "claude", "copilot", "fine-tun", "inference", "dataset", "pipeline",
    ],
    "priority_categories": ["mcp-servers", "ai-agents", "rag-kb",
                            "agent-orchestration", "llm-prompts",
                            "ai-dev-tools", "data-infra", "developer-tools"],
}

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "reserve_rules.json"


def load_rules() -> dict:
    if RULES_PATH.exists():
        try:
            user = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            merged = json.loads(json.dumps(DEFAULT_RULES))
            merged.update(user)
            for k, v in user.items():
                if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
                    merged[k].update(v)
            return merged
        except Exception as e:
            print(f"[rules] failed to load {RULES_PATH}: {e}")
    return json.loads(json.dumps(DEFAULT_RULES))


def save_default_rules() -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not RULES_PATH.exists():
        RULES_PATH.write_text(json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[rules] wrote default rules -> {RULES_PATH}")


# ============================================================
# 生态匹配
# ============================================================

def eco_match_score(repo: dict, rules: dict) -> float:
    """生态匹配度 0~1: 在 名称/描述/topics/分类/功能标签 中命中生态关键词的比例。"""
    keywords = rules.get("ecosystem_keywords", [])
    if not keywords:
        return 0.0
    topics = repo.get("topics")
    topics = topics if topics is not None else []
    tags = repo.get("function_tags")
    tags = tags if tags is not None else []
    haystack = " ".join(filter(None, [
        repo.get("name", ""), repo.get("full_name", ""),
        repo.get("description", ""), repo.get("description_zh", ""),
        " ".join([str(t) for t in topics]),
        " ".join([str(t) for t in tags]),
        repo.get("category", ""),
    ])).lower()
    hits = [k for k in keywords if k in haystack]
    score = min(1.0, len(hits) / 3.0)  # 命中 3 个即满分
    return round(score, 3)


# ============================================================
# 功能索引 (LLM / 启发式)
# ============================================================

FUNCTION_TAG_RULES = [
    (["mcp", "model-context-protocol", "mcp-server"], ["MCP"]),
    (["agent", "multi-agent", "autogen", "crewai", "langgraph"], ["AI-Agent"]),
    (["rag", "retrieval", "knowledge", "vector", "embedding", "document"], ["RAG", "知识库"]),
    (["llm", "gpt", "claude", "gemini", "prompt"], ["LLM"]),
    (["code", "coding", "ide", "copilot", "compiler"], ["AI-编程"]),
    (["database", "db", "sql", "parquet", "duckdb", "warehouse"], ["数据基础设施"]),
    (["cli", "command", "terminal", "shell"], ["CLI工具"]),
    (["awesome", "list", "collection"], ["资源索引"]),
    (["search", "index", "retrieval"], ["搜索/检索"]),
    (["api", "sdk", "framework", "library"], ["SDK/框架"]),
]


def heuristic_function_index(repo: dict) -> dict:
    """无 LLM key 时的启发式功能索引 (可配置降级)。"""
    text = " ".join(filter(None, [
        repo.get("description", ""), " ".join(repo.get("topics", []) or []),
        repo.get("name", ""), repo.get("category", ""),
    ])).lower()
    tags: list[str] = []
    for keywords, tag in FUNCTION_TAG_RULES:
        if any(k in text for k in keywords) and tag[0] not in tags:
            tags.extend(tag)
    if not tags:
        tags = ["未分类"]
    # 一句话总结: 从描述截取 (中文优先)
    summary = repo.get("description_zh") or repo.get("description") or ""
    if len(summary) > 120:
        summary = summary[:117] + "..."
    lang = repo.get("language") or "未知"
    category = repo.get("category") or "通用"
    use_case = f"适合在「{category}」场景下使用；语言 {lang}；主要能力: {'、'.join(tags)}"
    return {
        "function_tags": tags,
        "function_summary": summary,
        "use_case": use_case,
        "ecosystem_fit": f"命中生态关键词 {len([k for k in ['mcp','agent','rag','llm','vector'] if k in text])}/5 项",
    }


def llm_function_index(repo: dict, client=None) -> dict | None:
    """LLM 功能索引 (有 provider 时启用, 无则返回 None 由启发式兜底)。

    client: 可选回调 fn(repo) -> {function_tags, function_summary, use_case, ecosystem_fit}
    默认使用 reserve.llm.get_provider() 的 OpenAI 兼容 / 本地 Ollama 接入。
    """
    if client is None:
        try:
            from reserve.enrich import enrich_one
            from reserve.llm import get_provider
            provider = get_provider()
            if provider is None:
                return None
            out = enrich_one(repo, provider=provider, use_cache=False)
            if out.get("index_source") != "llm":
                return None
            return {
                "function_tags": out.get("function_tags"),
                "function_summary": out.get("function_summary"),
                "use_case": out.get("use_case"),
                "ecosystem_fit": out.get("ecosystem_fit"),
            }
        except Exception as e:
            print(f"[classifier] llm index error: {e}")
            return None
    try:
        return client(repo)
    except Exception as e:
        print(f"[classifier] llm index error: {e}")
        return None


# ============================================================
# 打分与分类
# ============================================================

def score_repo(repo: dict, rules: dict) -> dict:
    """按调研报告 §5.3 打分 -> 返回 {score, signals, eco_match, decision, reason}。"""
    w = rules.get("weights", {})
    dt = rules.get("delta_thresholds", {})
    score = 0
    signals: list[str] = []

    d24 = repo.get("stars_delta_24h") or 0
    d7 = repo.get("stars_delta_7d") or 0
    stars = repo.get("stars") or 0

    if d24 >= dt.get("delta_24h_burst", 500):
        score += w.get("delta_24h_burst", 3)
        signals.append(f"24h 爆发 +{d24}")
    if d7 >= dt.get("delta_7d_burst", 2000):
        score += w.get("delta_7d_burst", 3)
        signals.append(f"7d 走红 +{d7}")
    if repo.get("is_new_this_week"):
        score += w.get("new_this_week", 1)
        signals.append("当周新仓库")
    if stars >= dt.get("stable_stars", 10000):
        score += w.get("stable_high_stars", 1)
        signals.append(f"稳定高星 {stars}")

    eco = eco_match_score(repo, rules)
    if eco >= rules.get("thresholds", {}).get("eco_match", 0.5):
        score += w.get("eco_match", 2)
        signals.append(f"生态匹配 {eco}")

    if repo.get("license") and _pushed_recent(repo, dt.get("active_pushed_days", 30)):
        score += w.get("quality_active", 1)
        signals.append("活跃且协议明确")
    if not repo.get("archived"):
        score += w.get("quality_not_archived", 1)
        signals.append("未归档")

    return {"score": score, "signals": signals, "eco_match": eco}


def _pushed_recent(repo: dict, days: int) -> bool:
    from datetime import datetime, timezone, timedelta
    pushed = repo.get("pushed_at")
    if not pushed:
        return False
    try:
        t = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).days <= days
    except Exception:
        return False


def classify(repo: dict, rules: dict | None = None) -> dict:
    """单仓库分类 -> 填充 category_decision / decision_score / decision_reason。"""
    rules = rules or load_rules()
    th = rules.get("thresholds", {})
    action_th = th.get("action", 7)
    reserve_th = th.get("reserve", 4)
    eco_th = th.get("eco_match", 0.5)

    res = score_repo(repo, rules)
    score = res["score"]
    eco = res["eco_match"]

    if score >= action_th and eco >= eco_th:
        decision, reason = "action", f"生态升级: 增长分{score} + 生态匹配{eco} ({'; '.join(res['signals'])})"
    elif score >= reserve_th:
        decision, reason = "reserve", f"储备索引: 增长分{score} (未达 action 阈值{action_th}) ({'; '.join(res['signals'])})"
    elif eco >= eco_th:
        decision, reason = "partial", f"部分采用: 生态匹配{eco} 但增长分{score}不足 ({'; '.join(res['signals'])})"
    else:
        decision, reason = "ignore", f"忽略: 增长分{score} + 生态匹配{eco} 均不足"

    repo["category_decision"] = decision
    repo["decision_score"] = float(score)
    repo["decision_reason"] = reason

    # 功能索引 (LLM 优先, 启发式兜底)
    idx = llm_function_index(repo)
    if idx:
        for k, v in idx.items():
            repo[k] = v
    elif not repo.get("function_tags"):
        idx = heuristic_function_index(repo)
        repo.update(idx)
    return repo


def classify_batch(repos: list[dict], rules: dict | None = None) -> list[dict]:
    rules = rules or load_rules()
    out = []
    for r in repos:
        out.append(classify(r, rules))
    # 统计
    from collections import Counter
    counter = Counter(r["category_decision"] for r in out)
    print(f"[classifier] decisions: {dict(counter)}")
    return out


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="条件判断分类 + 功能索引")
    parser.add_argument("input", nargs="?", help="归一化 JSON (preprocessor 输出)")
    parser.add_argument("--out", default=None, help="输出路径")
    args = parser.parse_args()

    save_default_rules()
    if args.input:
        in_path = Path(args.input)
    else:
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        in_path = Path(__file__).resolve().parent.parent / "data" / "processed" / f"{today}.json"
    if not in_path.exists():
        print(f"[classifier] input not found: {in_path}")
        return 1

    data = json.loads(in_path.read_text(encoding="utf-8"))
    repos = data.get("records") or data.get("new") or data
    if isinstance(repos, dict):
        repos = list(repos.values())

    rules = load_rules()
    classified = classify_batch(repos, rules)

    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + ".classified.json")
    out_path.write_text(json.dumps({"date": in_path.stem, "repos": classified},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[classifier] wrote {out_path} ({len(classified)} repos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
