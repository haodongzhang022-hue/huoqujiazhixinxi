"""reserve/dashboard.py — 内容结构化整理模块（"当前获取的内容应该好好整理，有结构，然后再把内容到页面"）

回答用户核心诉求：**获取的内容要有结构、整理好，再展示到页面**。

本模块把储备库/快照/质量数据整理为页面友好的结构化视图：

  1. overview      总览: 总量 / 分类分布 / 决策分布 / 质量分 / 趋势摘要
  2. repos         仓库列表: 分页 + 过滤 (decision / category / tag / q)
  3. clusters      能力簇: 按 function_tags 聚类 (复用 cluster.py, 补充分页/统计)
  4. quality       质量: 快照/储备库/趋势 质量报告
  5. needs         待满足需求 (pending_needs)
  6. review_queue  人工审核队列
  7. snapshot      每日快照列表 (从 data/snapshots/*.json 或快照表)

每个视图返回纯 dict（JSON 可序列化）, 供 web 页面与 REST API 共用。
CLI 用法:
  python -m reserve.dashboard --overview
  python -m reserve.dashboard --repos --decision reserve --limit 20
  python -m reserve.dashboard --clusters
  python -m reserve.dashboard --quality
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from reserve.store import ReserveStore, rows_to_dicts
from reserve.quality import assess_snapshot, assess_store, assess_trend, build_report

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "pipeline" / "data" / "snapshots"


def _json_clean(obj):
    """递归清理 numpy 类型 -> 原生类型。"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _repo_card(r: dict) -> dict:
    """仓库 -> 页面卡片（精简字段, 避免 embedding 大数组）。"""
    return {
        "full_name": r.get("full_name"),
        "name": r.get("name"),
        "url": r.get("url"),
        "description": r.get("description"),
        "description_zh": r.get("description_zh"),
        "language": r.get("language"),
        "stars": r.get("stars"),
        "stars_delta_24h": r.get("stars_delta_24h"),
        "stars_delta_7d": r.get("stars_delta_7d"),
        "is_new_this_week": r.get("is_new_this_week"),
        "category": r.get("category"),
        "category_decision": r.get("category_decision"),
        "decision_score": r.get("decision_score"),
        "decision_reason": r.get("decision_reason"),
        "function_tags": r.get("function_tags") or [],
        "function_summary": r.get("function_summary"),
        "use_case": r.get("use_case"),
        "ecosystem_fit": r.get("ecosystem_fit"),
        "index_source": r.get("index_source"),
        "review_status": r.get("review_status"),
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
        "license": r.get("license"),
        "first_seen_at": r.get("first_seen_at"),
        "source": r.get("source"),
        "matched_needs": r.get("matched_needs") or [],
    }


# ============================================================
# 视图: 总览
# ============================================================

def overview(store: ReserveStore | None = None, days: int = 7) -> dict:
    """总览视图: 储备库总量 / 分类 / 决策 / 质量 / 快照 / 需求。"""
    store = store or ReserveStore()
    repos = store.all_repos(limit=100000)

    decisions = Counter(r.get("category_decision") or "none" for r in repos)
    categories = Counter(r.get("category") or "unknown" for r in repos)
    tags_counter: Counter = Counter()
    for r in repos:
        for t in (r.get("function_tags") or []):
            tags_counter[str(t)] += 1

    # 质量
    quality = {
        "store": assess_store(store),
        "trend": assess_trend(days=days),
    }

    # 快照: 今日 + 最近 N 天
    snapshots = []
    for p in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)[:days]:
        rep = assess_snapshot(p)
        if "error" not in rep:
            snapshots.append({
                "date": rep["date"],
                "score": rep["score"],
                "grade": rep["grade"]["grade"],
                "total": rep["stats"]["total"],
                "unique": rep["stats"]["unique"],
                "new_this_week": rep["stats"]["new_this_week"],
                "action_candidates": rep["stats"]["action_candidates"],
            })

    # 需求 & 审核队列
    needs = store.needs_get()
    open_needs = [n for n in needs if n.get("status") != "matched"]
    matched_needs = [n for n in needs if n.get("status") == "matched"]
    try:
        from reserve.review import queue_list
        review_queue = queue_list()
        review_pending = [q for q in review_queue if q.get("status") == "pending"]
        review_approved = [q for q in review_queue if q.get("status") == "approved"]
    except Exception:
        review_pending = review_approved = []

    return {
        "mode": "overview",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_repos": len(repos),
            "decisions": dict(decisions),
            "categories": dict(categories.most_common()),
            "top_tags": tags_counter.most_common(20),
            "needs": {"total": len(needs), "open": len(open_needs), "matched": len(matched_needs)},
            "review": {"pending": len(review_pending), "approved": len(review_approved)},
        },
        "quality": {
            "store_score": quality["store"].get("score"),
            "store_grade": quality["store"].get("grade", {}).get("grade"),
            "store_issues": quality["store"].get("issues", [])[:5],
            "trend": quality["trend"].get("points", []),
            "trend_direction": quality["trend"].get("direction"),
            "trend_avg": quality["trend"].get("avg_score"),
        },
        "snapshots": snapshots,
        "review_queue_preview": review_pending[:10],
        "needs_preview": open_needs[:10],
    }


# ============================================================
# 视图: 仓库列表
# ============================================================

def repos_view(store: ReserveStore | None = None, decision: str | None = None,
               category: str | None = None, tag: str | None = None,
               q: str | None = None, limit: int = 50, offset: int = 0,
               sort: str = "stars") -> dict:
    """仓库列表视图（分页 + 过滤 + 排序）。"""
    store = store or ReserveStore()
    where = None
    filters = []
    if decision:
        filters.append(f"category_decision = '{decision}'")
    if category:
        filters.append(f"category = '{category}'")
    if tag:
        filters.append(f"function_tags LIKE '%{tag}%'")
    if filters:
        where = " AND ".join(filters)

    # 过滤 + 排序
    rows = store.query(where=where, limit=100000)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r.get("full_name") or "").lower()
                or ql in (r.get("description") or "").lower()
                or ql in " ".join(r.get("function_tags") or []).lower()
                or ql in (r.get("function_summary") or "").lower()]
    if sort == "stars":
        rows.sort(key=lambda r: r.get("stars") or 0, reverse=True)
    elif sort == "newest":
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    elif sort == "score":
        rows.sort(key=lambda r: r.get("decision_score") or 0, reverse=True)
    elif sort == "delta7d":
        rows.sort(key=lambda r: r.get("stars_delta_7d") or 0, reverse=True)

    total = len(rows)
    page = rows[offset:offset + limit]
    return {
        "mode": "repos",
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {"decision": decision, "category": category, "tag": tag, "q": q, "sort": sort},
        "items": [_repo_card(r) for r in page],
    }


# ============================================================
# 视图: 能力簇
# ============================================================

def clusters_view(store: ReserveStore | None = None, mode: str = "by-tags",
                  k: int = 6, limit: int = 30) -> dict:
    """能力簇视图（复用 reserve.cluster）。"""
    try:
        from reserve.cluster import cluster_by_tags, kmeans, load_repos as cluster_load_repos
        # cluster.load_repos 不接受 store 参数, 这里直接用传入 store 的数据
        if store is not None:
            repos = store.all_repos(limit=100000)
        else:
            repos = cluster_load_repos(limit=100000)
        # 未分类 -> 补齐 (与 cluster.load_repos 行为一致)
        unclassified = [r for r in repos if not r.get("function_tags") or not r.get("category_decision")]
        if unclassified:
            from reserve.classifier import classify_batch
            enriched = classify_batch(unclassified)
            by_name = {r.get("full_name"): r for r in enriched}
            repos = [by_name.get(r.get("full_name"), r) for r in repos]
        if mode == "kmeans":
            result = kmeans(repos, k=k)
        else:
            result = cluster_by_tags(repos)
        # 限制每簇项目数
        for cl in result.get("clusters", []):
            cl["repos"] = cl.get("repos", [])[:limit]
        result["mode"] = f"dashboard-{mode}"
        return _json_clean(result)
    except Exception as e:
        return {"mode": "clusters", "error": str(e), "clusters": []}


# ============================================================
# 视图: 质量
# ============================================================

def quality_view(days: int = 7, snapshot: str | Path | None = None,
                 store: ReserveStore | None = None) -> dict:
    """质量视图: 快照 + 储备库 + 趋势 综合。"""
    report = build_report(days=days, store=store, snapshot=snapshot)
    return _json_clean(report)


# ============================================================
# 视图: 需求 & 审核队列
# ============================================================

def needs_view(store: ReserveStore | None = None) -> dict:
    store = store or ReserveStore()
    needs = store.needs_get()
    return {
        "mode": "needs",
        "total": len(needs),
        "items": needs,
    }


def review_view() -> dict:
    try:
        from reserve.review import queue_list
        q = queue_list()
        return {
            "mode": "review_queue",
            "total": len(q),
            "pending": sum(1 for e in q if e.get("status") == "pending"),
            "approved": sum(1 for e in q if e.get("status") == "approved"),
            "rejected": sum(1 for e in q if e.get("status") == "rejected"),
            "items": q,
        }
    except Exception as e:
        return {"mode": "review_queue", "error": str(e), "items": []}


# ============================================================
# 视图: 快照
# ============================================================

def snapshots_view(days: int = 14, store: ReserveStore | None = None) -> dict:
    """每日快照列表（日期 / 数量 / 质量分）。"""
    items = []
    for p in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)[:days]:
        rep = assess_snapshot(p)
        if "error" in rep:
            continue
        items.append({
            "date": rep["date"],
            "score": rep["score"],
            "grade": rep["grade"]["grade"],
            "total": rep["stats"]["total"],
            "unique": rep["stats"]["unique"],
            "new_this_week": rep["stats"]["new_this_week"],
            "action_candidates": rep["stats"]["action_candidates"],
            "categories": rep["stats"]["categories"],
            "issues": rep.get("issues", [])[:3],
        })
    return {"mode": "snapshots", "total": len(items), "items": items}


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="储备库结构化整理视图")
    parser.add_argument("--overview", action="store_true", help="总览")
    parser.add_argument("--repos", action="store_true", help="仓库列表")
    parser.add_argument("--clusters", action="store_true", help="能力簇")
    parser.add_argument("--quality", action="store_true", help="质量")
    parser.add_argument("--needs", action="store_true", help="需求")
    parser.add_argument("--review", action="store_true", help="审核队列")
    parser.add_argument("--snapshots", action="store_true", help="每日快照")
    parser.add_argument("--decision", default=None, choices=["action", "reserve", "partial", "ignore"])
    parser.add_argument("--category", default=None)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--q", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sort", default="stars", choices=["stars", "newest", "score", "delta7d"])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default=None, help="输出 JSON 到文件")
    args = parser.parse_args()

    if args.overview:
        data = overview(days=args.days)
    elif args.repos:
        data = repos_view(decision=args.decision, category=args.category, tag=args.tag,
                          q=args.q, limit=args.limit, offset=args.offset, sort=args.sort)
    elif args.clusters:
        data = clusters_view(mode="by-tags")
    elif args.quality:
        data = quality_view(days=args.days)
    elif args.needs:
        data = needs_view()
    elif args.review:
        data = review_view()
    elif args.snapshots:
        data = snapshots_view(days=args.days)
    else:
        parser.print_help()
        return 1

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[dashboard] wrote {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
