"""入库管道 (ingest.py) —— fetch -> preprocess -> classify -> embed -> LanceDB。

端到端一步到位: 吃快照 JSON, 产出储备库记录 + 每日快照表 + 决策统计。

用法:
  python -m reserve.ingest [--snapshot pipeline/data/snapshots/YYYY-MM-DD.json]
                           [--dry-run] [--no-snapshot]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from reserve.preprocessor import load_snapshot, dedupe
from reserve.classifier import classify_batch, load_rules, save_default_rules
from reserve.embedding import embed_batch
from reserve.store import ReserveStore, now_iso
from reserve.llm import get_provider, describe_config, save_default_config

ROOT = Path(__file__).resolve().parent.parent


def _default_snapshot() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ROOT / "pipeline" / "data" / "snapshots" / f"{today}.json"


def run(snapshot: Path, dry_run: bool = False, write_snapshot: bool = True,
        llm_enrich: bool = True, llm_review: bool = True,
        fetch_readme: bool = True, readme_provider=None) -> dict:
    """端到端管道: fetch 快照 -> 归一化 -> 去重 -> 分类 -> (LLM 功能索引) -> 向量化 -> 入库 -> (LLM 代码审核)。

    llm_enrich:  是否启用 LLM 功能索引增强 (无 LLM 配置自动降级启发式)
    llm_review:  是否对 action 候选启用 LLM 代码审核 + 人工审核队列
    fetch_readme: 增强/审核时是否拉取 README (消耗 GitHub 配额)
    """
    if not snapshot.exists():
        print(f"[ingest] snapshot not found: {snapshot}", file=sys.stderr)
        return {"error": f"snapshot not found: {snapshot}"}

    # 0. 确保默认配置文件存在 (config/llm.json)
    save_default_config()

    # 1. 归一化
    repos = load_snapshot(snapshot)
    print(f"[ingest] ① loaded {len(repos)} records from {snapshot.name}")

    # 2. 去重 (内存 + 储备库)
    store = None if dry_run else ReserveStore()
    result = dedupe(repos, store)
    new, existing = result["new"], result["existing"]
    print(f"[ingest] ② dedupe: new={len(new)} existing={len(existing)} skipped_secondary="
          f"{len(repos) - len(result['records'])}")

    # 3. 分类 + 功能索引 (LLM 优先, 无配置启发式兑底)
    rules = load_rules()
    classified = classify_batch(new, rules)
    print(f"[ingest] ③ classified {len(classified)} new repos")

    # 3.5 LLM 功能索引增强 (读 README/发布者介绍 -> function_tags/summary/use_case)
    llm_info = describe_config()
    if llm_enrich:
        from reserve.enrich import enrich_repos
        print(f"[ingest] ③.5 LLM 功能索引增强 ... ({llm_info})")
        enrich_repos(classified, fetch_readme=fetch_readme,
                     readme_provider=readme_provider)

    # 4. 向量化
    embeddings = embed_batch(classified)
    for r, emb in zip(classified, embeddings):
        r["embedding"] = emb
    print(f"[ingest] ④ embedded {len(classified)} repos (dim={len(embeddings[0]) if embeddings else '-'})")

    # 4.5 LLM 代码审核 (action 候选 -> review 四维评审 + 人工审核队列, 审核结果随行入库)
    if llm_review and not dry_run:
        from reserve.review import review_action_candidates
        try:
            review_action_candidates(classified, fetch_readme=fetch_readme,
                                     readme_provider=readme_provider)
        except Exception as e:
            print(f"[ingest] review step error (non-fatal): {e}")

    if dry_run:
        return {
            "dry_run": True,
            "total_loaded": len(repos),
            "new": len(new),
            "existing": len(existing),
            "decisions": _count_decisions(classified),
            "sample": classified[:3],
        }

    # 5. 入库
    stats = store.upsert_repos(classified)
    print(f"[ingest] ⑤ upsert: {stats}")

    # 6. 每日快照表
    if write_snapshot:
        date = snapshot.stem
        store.snapshot_put(date, classified, meta={"ingest_ts": now_iso()})
        print(f"[ingest] ⑥ snapshot {date}: {len(classified)} rows")

    return {
        "date": snapshot.stem,
        "total_loaded": len(repos),
        "new": len(new),
        "existing": len(existing),
        "upsert": stats,
        "decisions": _count_decisions(classified),
        "reserve_total": store.count(),
    }


def _count_decisions(repos: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(r.get("category_decision", "none") for r in repos))


def main() -> int:
    parser = argparse.ArgumentParser(description="储备库入库管道 (fetch->classify->embed->LanceDB)")
    parser.add_argument("--snapshot", default=None, help="快照 JSON 路径 (默认今日)")
    parser.add_argument("--dry-run", action="store_true", help="只处理不落库")
    parser.add_argument("--no-snapshot", action="store_true", help="不写每日快照表")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM 功能索引增强")
    parser.add_argument("--no-review", action="store_true", help="禁用 LLM 代码审核")
    parser.add_argument("--no-readme", action="store_true", help="不拉取 README (省 GitHub 配额)")
    args = parser.parse_args()

    save_default_rules()
    snap = Path(args.snapshot) if args.snapshot else _default_snapshot()
    result = run(snap, dry_run=args.dry_run, write_snapshot=not args.no_snapshot,
                 llm_enrich=not args.no_llm, llm_review=not args.no_review,
                 fetch_readme=not args.no_readme)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
