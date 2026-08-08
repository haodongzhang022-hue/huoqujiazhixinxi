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

ROOT = Path(__file__).resolve().parent.parent


def _default_snapshot() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ROOT / "pipeline" / "data" / "snapshots" / f"{today}.json"


def run(snapshot: Path, dry_run: bool = False, write_snapshot: bool = True) -> dict:
    if not snapshot.exists():
        print(f"[ingest] snapshot not found: {snapshot}", file=sys.stderr)
        return {"error": f"snapshot not found: {snapshot}"}

    # 1. 归一化
    repos = load_snapshot(snapshot)
    print(f"[ingest] ① loaded {len(repos)} records from {snapshot.name}")

    # 2. 去重 (内存 + 储备库)
    store = None if dry_run else ReserveStore()
    result = dedupe(repos, store)
    new, existing = result["new"], result["existing"]
    print(f"[ingest] ② dedupe: new={len(new)} existing={len(existing)} skipped_secondary="
          f"{len(repos) - len(result['records'])}")

    # 3. 分类 + 功能索引
    rules = load_rules()
    classified = classify_batch(new, rules)
    print(f"[ingest] ③ classified {len(classified)} new repos")

    # 4. 向量化
    embeddings = embed_batch(classified)
    for r, emb in zip(classified, embeddings):
        r["embedding"] = emb
    print(f"[ingest] ④ embedded {len(classified)} repos (dim={len(embeddings[0]) if embeddings else '-'})")

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
    args = parser.parse_args()

    save_default_rules()
    snap = Path(args.snapshot) if args.snapshot else _default_snapshot()
    result = run(snap, dry_run=args.dry_run, write_snapshot=not args.no_snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
