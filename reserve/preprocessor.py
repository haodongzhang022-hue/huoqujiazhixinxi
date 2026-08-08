"""数据预处理 (preprocessor.py) —— 真实抓取快照 -> 归一化 -> 去重 -> 待入库记录。

对齐调研报告 §5.1 数据流的第 ①② 步:
  ① 归一化: 统一 schema (full_name/desc/topics/lang/stars/deltas/created)
  ② 去重  : 与储备库已有记录按 full_name 去重 (增量入库)

输入: pipeline/data/snapshots/YYYY-MM-DD.json (fetch 层输出)
    或任意符合 {repos: [...]} / {items: [...]} 结构的 JSON 文件
输出: 归一化 + 去重后的仓库记录列表 (供 classifier / ingest)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from reserve.store import ReserveStore


def normalize_repo(raw: dict, category: str | None = None) -> dict:
    """把 fetch 快照中的原始记录归一化为储备库标准字段。

    兼容两版 fetch 输出:
      - pipeline/fetch.py (v2.1): 已有 repo_id/stars/stars_delta_24h/... 字段
      - scripts/fetch.py (v1):   stargazers_count/stars_delta_* 由历史快照算
    """
    full_name = raw.get("full_name") or raw.get("repo_id") or ""
    if not full_name:
        return {}
    desc = raw.get("description") or ""
    repo = {
        "repo_id": full_name,
        "full_name": full_name,
        "name": raw.get("name") or full_name.split("/")[-1],
        "owner": raw.get("owner") or full_name.split("/")[0],
        "url": raw.get("url") or raw.get("html_url") or f"https://github.com/{full_name}",
        "homepage": raw.get("homepage") or "",
        "description": desc,
        "description_zh": raw.get("description_zh"),
        "language": raw.get("language") or "",
        "topics": raw.get("topics") or [],
        "stars": int(raw.get("stars", raw.get("stargazers_count", 0)) or 0),
        "forks": int(raw.get("forks", raw.get("forks_count", 0)) or 0),
        "stars_delta_24h": raw.get("stars_delta_24h"),
        "stars_delta_7d": raw.get("stars_delta_7d"),
        "forks_delta_7d": raw.get("forks_delta_7d"),
        "delta_window_days": raw.get("delta_window_days"),
        "is_new_this_week": bool(raw.get("is_new_this_week", False)),
        "created_at": raw.get("created_at") or "",
        "pushed_at": raw.get("pushed_at") or "",
        "first_seen_at": raw.get("first_seen_at") or datetime.now(timezone.utc).isoformat(),
        "source": raw.get("source") or ["fetch"],
        "category": category or raw.get("category"),
        "categories": raw.get("categories") or ([category] if category else []),
        "action_candidate": bool(raw.get("action_candidate", False)),
        "delta_source": raw.get("delta_source", "none"),
        "is_secondary": bool(raw.get("is_secondary", False)),
        "matched_needs": raw.get("matched_needs") or [],
        "matched_scores": raw.get("matched_scores") or [],
        # 功能索引/分类 占位 (由 classifier 填充)
        "function_tags": raw.get("function_tags") or [],
        "function_summary": raw.get("function_summary"),
        "use_case": raw.get("use_case"),
        "ecosystem_fit": raw.get("ecosystem_fit"),
        "category_decision": raw.get("category_decision"),
        "decision_score": raw.get("decision_score"),
        "decision_reason": raw.get("decision_reason"),
    }
    return repo


def load_snapshot(path: str | Path) -> list[dict]:
    """读取快照 JSON -> 归一化仓库列表。

    支持:
      - {repos: [...], categories: [...]} (pipeline/fetch.py v2.1 结构)
      - {items: [...], categories: [...]}  (scripts/fetch.py v1 结构)
      - 直接是列表
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("repos") or data.get("items") or []

    # 若分类分组的 categories 里才有 items (两版都含 categories 分组), 补充收集
    cat_map: dict[str, str] = {}
    for cat in data.get("categories", []) if isinstance(data, dict) else []:
        for it in cat.get("items", []):
            fn = it.get("full_name") or it.get("repo_id")
            if fn:
                cat_map[fn] = cat.get("category") or cat.get("id") or ""

    out = []
    for raw in items:
        fn = raw.get("full_name") or raw.get("repo_id")
        cat = raw.get("category") or cat_map.get(fn or "")
        repo = normalize_repo(raw, category=cat)
        if repo:
            out.append(repo)
    return out


def dedupe(repos: list[dict], store: ReserveStore | None = None) -> dict:
    """去重:
      1. 内存去重: 同一 full_name 多条记录 -> 保留主记录 (is_secondary=False)
      2. 与储备库去重: 已入库的 full_name -> 标记 exists (增量跳过/更新)
    返回: {"new": [...], "existing": [...], "records": [...]}
    """
    by_name: dict[str, dict] = {}
    for r in repos:
        fn = r["full_name"]
        prev = by_name.get(fn)
        if prev is None or r.get("stars", 0) > prev.get("stars", 0):
            if prev is not None:
                prev["is_secondary"] = True
            r["is_secondary"] = False
            by_name[fn] = r
        else:
            r["is_secondary"] = True

    existing_names: set[str] = set()
    if store is not None:
        try:
            existing_names = store._all_repo_ids()
        except Exception:
            existing_names = set()

    records = [r for r in by_name.values() if not r.get("is_secondary")]
    new = [r for r in records if r["full_name"] not in existing_names]
    existing = [r for r in records if r["full_name"] in existing_names]
    return {
        "new": new,
        "existing": existing,
        "records": records,
        "existing_names": existing_names,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="快照归一化 + 去重")
    parser.add_argument("snapshot", nargs="?", help="快照 JSON 路径 (默认 pipeline/data/snapshots/今日.json)")
    parser.add_argument("--out", default=None, help="输出归一化 JSON 路径 (默认 data/processed/今日.json)")
    parser.add_argument("--check-existing", action="store_true", help="与 LanceDB 储备库核对去重")
    args = parser.parse_args()

    if args.snapshot:
        snap_path = Path(args.snapshot)
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap_path = Path(__file__).resolve().parent.parent / "pipeline" / "data" / "snapshots" / f"{today}.json"
    if not snap_path.exists():
        print(f"[preprocess] snapshot not found: {snap_path}")
        return 1

    repos = load_snapshot(snap_path)
    print(f"[preprocess] loaded {len(repos)} records from {snap_path.name}")

    store = ReserveStore() if args.check_existing else None
    result = dedupe(repos, store)
    new, existing = result["new"], result["existing"]
    print(f"[preprocess] new={len(new)} existing={len(existing)} (total unique={len(result['records'])})")

    out_path = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "data" / "processed" / f"{snap_path.stem}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"date": snap_path.stem, "new": new, "existing": existing, "records": result["records"]},
                  f, ensure_ascii=False, indent=2)
    print(f"[preprocess] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
