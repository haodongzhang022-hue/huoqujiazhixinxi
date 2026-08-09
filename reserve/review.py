"""reserve/review.py — LLM 代码审核 / 生态升级审核（读 README + 仓库元数据 → 四维评审）

用户核心诉求落地点之二：
  「这部分似乎需要引入大模型进行代码审核实现，或者看项目发布者的介绍」

对 **action 候选（生态升级）** 仓库做四维评审，决定是否值得吸收进生态：

  1. 功能匹配     —— 是否真的解决我们要的问题（功能索引交叉验证）
  2. 代码质量     —— README 呈现的结构、活跃度、star 增长、协议、维护状态
  3. 许可证/合规  —— license 是否可商用（MIT/Apache/BSD 优, GPL 提示, 无协议告警）
  4. 生态适配     —— 与 MCP/AI-Agent/RAG/LLM 生态的对接难度、依赖风险

输出 `review` 结构（写入 repo, 同时进入人工审核队列 review_queue）:
  {
    "verdict": "approve / condition / reject / manual",   # 建议
    "score": 0-10,                                       # 综合评分
    "risks": ["风险1", ...],
    "recommendation": "一句话建议",
    "reviewed_at": "..."
  }

人工审核队列（@CodeBuddy 入口）:
  - repo["review_status"] = "pending"  -> 等待人工/@CodeBuddy 审核
  - 审核人通过/拒绝后置为 "approved" / "rejected"
  - review_queue.json 持久化队列（config/review_queue.json）

用法:
  from reserve.review import review_repo, review_action_candidates
  review_action_candidates(repos, fetch_readme=True)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from reserve.llm import get_provider, describe_config

QUEUE_PATH = Path(os.environ.get("REVIEW_QUEUE", "")) if os.environ.get("REVIEW_QUEUE") \
    else Path(__file__).resolve().parent.parent / "config" / "review_queue.json"

_REVIEW_SYSTEM = """你是一名资深开源软件技术审核专家，负责评估一个开源项目是否值得被一个
「AI 生态团队」吸收为正式依赖（生态升级）。请根据仓库元数据和 README 内容，做四维评审，
并输出严格的 JSON（不要 markdown、不要解释）：

{
  "verdict": "approve 或 condition 或 reject 或 manual",
  "score": 8,
  "risks": ["风险点1", "风险点2"],
  "recommendation": "一句话综合建议"
}

评审维度：
1. 功能匹配：项目解决的问题是否明确、是否与描述的能力一致
2. 代码质量与活跃度：维护是否活跃（最近更新）、star 增长、文档是否完整
3. 许可证合规：license 是否可商用（MIT/Apache-2.0/BSD 优；GPL 类有传染性提示；无 license 告警）
4. 生态适配：接入 MCP/AI-Agent/RAG/LLM 生态的难度、依赖风险、是否过时

verdict 判定建议：
- approve   : 质量高、匹配强、协议友好、活跃，可直接吸收
- condition : 基本可用但有条件（如协议注意、缺文档、依赖重），需人工确认
- reject    : 明显不匹配/已归档/无维护/协议问题
- manual    : 信息不足或情况复杂，需要人工/@CodeBuddy 审核
score 为 0-10 整数。"""


def review_one(repo: dict, readme: str | None = None, provider=None) -> dict | None:
    """单仓库 LLM 审核 -> 返回 review dict；无 provider 返回 None（走人工队列）。"""
    provider = provider or get_provider()
    if provider is None:
        return None

    topics = repo.get("topics") or []
    parts = [
        f"仓库: {repo.get('full_name', '')}",
        f"语言: {repo.get('language') or '未知'}",
        f"Star: {repo.get('stars', 0)}  | 24h增量: {repo.get('stars_delta_24h')} | 7d增量: {repo.get('stars_delta_7d')}",
        f"license: {repo.get('license') or '无/未知'}",
        f"归档: {repo.get('archived', False)}",
        f"创建: {repo.get('created_at') or '未知'}",
        f"最近推送: {repo.get('pushed_at') or '未知'}",
        f"描述: {repo.get('description') or '(无)'}",
        f"主题: {', '.join(str(t) for t in topics) or '(无)'}",
        f"功能索引(现有): {repo.get('function_summary') or '(无)'}",
        f"适用场景: {repo.get('use_case') or '(无)'}",
        f"分类决策: {repo.get('category_decision')} | 得分: {repo.get('decision_score')}",
    ]
    if readme:
        parts.append(f"README(发布者介绍, 截断):\n{readme}")
    user = "\n".join(parts)

    out = provider.complete_json(_REVIEW_SYSTEM, user)
    if not out:
        print(f"[review] llm review failed for {repo.get('full_name')}")
        return None

    verdict = str(out.get("verdict") or "manual").strip().lower()
    if verdict not in ("approve", "condition", "reject", "manual"):
        verdict = "manual"
    try:
        score = int(float(out.get("score", 0)))
        score = max(0, min(10, score))
    except (TypeError, ValueError):
        score = 0
    risks = out.get("risks") or []
    if isinstance(risks, str):
        risks = [risks]
    risks = [str(r).strip()[:200] for r in risks if str(r).strip()][:6]
    return {
        "verdict": verdict,
        "score": score,
        "risks": risks,
        "recommendation": str(out.get("recommendation") or "").strip()[:300],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def _queue_load() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _queue_save(queue: list[dict]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def review_action_candidates(repos: list[dict], fetch_readme: bool = True,
                             readme_provider=None, force: bool = False) -> list[dict]:
    """对 action 候选仓库批量审核。

    - 审核结果写入 repo["review"]，并把 repo 加入 config/review_queue.json 人工审核队列
      （status=pending, 供 @CodeBuddy / 人工审核）
    - 无 LLM 时：直接进人工审核队列（review=None, status=pending）, 不阻塞管道
    - 已有 review 且 force=False -> 跳过

    参数:
      fetch_readme:     是否拉取 README 供审核（推荐, 审核质量更高）
      readme_provider:  自定义 fn(full_name)->str|None（默认 pipeline.github_client.get_readme）
      force:            强制重新审核已审过的仓库
    """
    provider = get_provider()
    if readme_provider is None:
        try:
            from pipeline.github_client import get_readme
            readme_provider = get_readme
        except Exception:
            readme_provider = None

    candidates = [r for r in repos
                  if r.get("category_decision") == "action"
                  or r.get("action_candidate")]
    if not candidates:
        return repos

    queue = _queue_load()
    queue_ids = {q.get("full_name") for q in queue}

    if provider is None:
        print(f"[review] 未配置 LLM, action 候选进入人工审核队列 ({len(candidates)} 个)。"
              f"配置方法: {describe_config()}")
    else:
        print(f"[review] LLM 审核 {len(candidates)} 个 action 候选 ({provider})")

    for r in candidates:
        fn = r.get("full_name") or ""
        if not fn:
            continue
        if not force and r.get("review") and not queue_ids:
            continue

        readme = None
        if fetch_readme and readme_provider is not None:
            try:
                readme = readme_provider(fn)
            except Exception as e:
                print(f"[review] readme error {fn}: {e}")

        review = review_one(r, readme=readme, provider=provider)
        r["review"] = review
        r["review_status"] = "pending" if review is None else "pending"

        # 入人工审核队列
        entry = {
            "full_name": fn,
            "url": r.get("url") or f"https://github.com/{fn}",
            "category_decision": r.get("category_decision"),
            "decision_score": r.get("decision_score"),
            "review": review,
            "status": "pending",   # pending / approved / rejected
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        if fn in queue_ids:
            queue = [q for q in queue if q.get("full_name") != fn]
        queue.append(entry)
        queue_ids.add(fn)

    _queue_save(queue)
    print(f"[review] 审核队列 -> {QUEUE_PATH} ({len(queue)} 个待审)")
    return repos


def queue_list() -> list[dict]:
    """查看人工审核队列。"""
    return _queue_load()


def queue_update(full_name: str, status: str, note: str = "", reviewer: str = "human") -> dict | None:
    """更新审核队列状态 (approve -> approved / reject -> rejected), 返回更新后的 entry。"""
    if status not in ("approved", "rejected"):
        raise ValueError("status must be approved/rejected")
    queue = _queue_load()
    for q in queue:
        if q.get("full_name") == full_name:
            q["status"] = status
            q["note"] = note
            q["reviewer"] = reviewer
            q["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            _queue_save(queue)
            return q
    return None


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="LLM 代码审核 / 生态升级审核")
    sub = parser.add_subparsers(dest="cmd")

    p_review = sub.add_parser("review", help="审核 action 候选")
    p_review.add_argument("input", help="分类后 JSON (含 category_decision)")
    p_review.add_argument("--no-readme", action="store_true", help="不拉 README")
    p_review.add_argument("--force", action="store_true")

    p_queue = sub.add_parser("queue", help="查看人工审核队列")
    p_queue.add_argument("--json", action="store_true")

    p_update = sub.add_parser("update", help="更新队列状态")
    p_update.add_argument("full_name")
    p_update.add_argument("status", choices=["approved", "rejected"])
    p_update.add_argument("--note", default="")
    p_update.add_argument("--reviewer", default="human")

    args = parser.parse_args()

    from reserve.llm import save_default_config
    save_default_config()

    if args.cmd == "review":
        from pathlib import Path
        from reserve.preprocessor import load_snapshot
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"input not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(in_path.read_text(encoding="utf-8"))
        repos = data.get("repos") or data.get("items") or (data if isinstance(data, list) else [])
        out = review_action_candidates(repos, fetch_readme=not args.no_readme, force=args.force)
        out_path = in_path.with_name(in_path.stem + ".reviewed.json")
        out_path.write_text(json.dumps({"repos": out}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out_path} ({len(out)} repos)")
        sys.exit(0)
    elif args.cmd == "queue":
        q = queue_list()
        if args.json:
            print(json.dumps(q, ensure_ascii=False, indent=2))
        else:
            for e in q:
                r = e.get("review") or {}
                print(f"- [{e['status']}] {e['full_name']} | {r.get('verdict')} "
                      f"score={r.get('score')} | {r.get('recommendation')}")
        sys.exit(0)
    elif args.cmd == "update":
        q = queue_update(args.full_name, args.status, note=args.note, reviewer=args.reviewer)
        print(json.dumps(q, ensure_ascii=False, indent=2) if q else "not found")
        sys.exit(0 if q else 1)
    else:
        parser.print_help()
        sys.exit(1)
