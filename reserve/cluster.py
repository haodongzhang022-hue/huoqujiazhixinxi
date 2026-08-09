"""能力聚类 (cluster.py) —— 对储备库项目做聚类, 输出「能力簇」视图。

背景 (Issue 需求): "我们进行这些数据的聚类 分类, 并列出他们的功能, 什么时候调用的能力"

本模块提供两种聚类视图:
  1. --by-tags (默认): 按功能标签 (function_tags) 聚合 -> 能力簇索引
      输出每个能力簇: {能力标签, 项目列表(含 stars/分类/功能摘要), 簇内总星数, 代表项目}
      直观回答 "生态里都有什么能力簇, 每个簇有哪些候选"
  2. --kmeans: 按 embedding 向量做轻量 K-means (纯 Python, 无 sklearn 依赖)
      输出语义簇 -> 每个簇的代表项目/主题词

用法:
  python -m reserve.cluster --by-tags                 # 按功能标签聚类
  python -m reserve.cluster --kmeans --k 6            # 向量 K-means
  python -m reserve.cluster --snapshot xxx.json       # 对快照/入库结果聚类 (不依赖储备库)
  python -m reserve.cluster --json
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from reserve.store import ReserveStore, rows_to_dicts
from reserve.embedding import embed_repo

ROOT = Path(__file__).resolve().parent.parent


def load_repos(source: str | None = None, limit: int = 10000) -> list[dict]:
    """加载储备库/快照中的仓库记录。

    若记录未生成功能索引/分类 (如原始 fetch 快照), 自动先过 classifier 补齐。
    """
    if source:
        from reserve.preprocessor import load_snapshot
        repos = load_snapshot(source)
    else:
        store = ReserveStore()
        repos = store.all_repos(limit=limit)
    # 未分类 -> 补齐 (LLM 可用则用, 否则启发式)
    unclassified = [r for r in repos if not r.get("function_tags") or not r.get("category_decision")]
    if unclassified:
        from reserve.classifier import classify_batch
        print(f"[cluster] enriching {len(unclassified)} unclassified repos...")
        enriched = classify_batch(unclassified)
        by_name = {r.get("full_name"): r for r in enriched}
        repos = [by_name.get(r.get("full_name"), r) for r in repos]
    return repos


# ============================================================
# 按功能标签聚类 (能力簇索引)
# ============================================================

def cluster_by_tags(repos: list[dict]) -> dict:
    """按 function_tags 聚合 -> 能力簇。

    返回 {"clusters": [{"tag", "count", "total_stars", "repos": [...]}], "summary": {...}}
    """
    clusters: dict[str, list[dict]] = defaultdict(list)
    for r in repos:
        tags = r.get("function_tags") or []
        for t in tags:
            clusters[str(t)].append(r)

    out = []
    for tag, items in clusters.items():
        total_stars = sum(int(r.get("stars") or 0) for r in items)
        items_sorted = sorted(items, key=lambda x: int(x.get("stars") or 0), reverse=True)
        out.append({
            "tag": tag,
            "count": len(items),
            "total_stars": total_stars,
            "avg_stars": round(total_stars / len(items), 1) if items else 0,
            "repos": [{
                "full_name": r.get("full_name"),
                "stars": r.get("stars"),
                "category": r.get("category"),
                "category_decision": r.get("category_decision"),
                "function_summary": r.get("function_summary"),
                "url": r.get("url"),
            } for r in items_sorted[:20]],
        })
    out.sort(key=lambda c: c["count"], reverse=True)

    # 汇总
    tag_counter: Counter = Counter()
    decision_counter: Counter = Counter()
    for r in repos:
        decision_counter[r.get("category_decision", "none")] += 1
        for t in (r.get("function_tags") or []):
            tag_counter[str(t)] += 1

    return {
        "mode": "by-tags",
        "clusters": out,
        "summary": {
            "total_repos": len(repos),
            "unique_tags": len(out),
            "top_tags": tag_counter.most_common(15),
            "decisions": dict(decision_counter),
        },
    }


# ============================================================
# 向量 K-means 聚类 (纯 Python, 无 sklearn)
# ============================================================

def _l2norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = _l2norm(a), _l2norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def kmeans(repos: list[dict], k: int = 6, max_iter: int = 20,
           seed: int = 42) -> dict:
    """基于仓库 embedding 的 K-means (余弦相似度, 手写实现)。"""
    if not repos:
        return {"mode": "kmeans", "clusters": [], "summary": {"total_repos": 0}}
    k = max(1, min(k, len(repos)))
    vecs = [embed_repo(r) for r in repos]
    dim = len(vecs[0]) if vecs else 0

    rng = random.Random(seed)
    # k-means++ 初始化
    centroids = [vecs[rng.randrange(len(vecs))]]
    for _ in range(1, k):
        dists = [1.0 - max(_cosine(v, c) for c in centroids) for v in vecs]
        total = sum(dists)
        if total <= 0:
            centroids.append(vecs[rng.randrange(len(vecs))])
            continue
        r = rng.random() * total
        acc = 0.0
        for i, d in enumerate(dists):
            acc += d
            if acc >= r:
                centroids.append(vecs[i])
                break

    assign = [0] * len(vecs)
    for _ in range(max_iter):
        changed = False
        for i, v in enumerate(vecs):
            best, best_sim = 0, -1.0
            for ci, c in enumerate(centroids):
                sim = _cosine(v, c)
                if sim > best_sim:
                    best, best_sim = ci, sim
            if assign[i] != best:
                assign[i] = best
                changed = True
        if not changed:
            break
        # 更新质心
        new_centroids = []
        for ci in range(k):
            members = [vecs[i] for i in range(len(vecs)) if assign[i] == ci]
            if not members:
                new_centroids.append(centroids[ci])
                continue
            d = dim or len(members[0])
            centroid = [sum(m[j] for m in members) / len(members) for j in range(d)]
            norm = _l2norm(centroid)
            new_centroids.append([x / norm for x in centroid] if norm else centroid)
        centroids = new_centroids

    # 组装结果
    groups: dict[int, list[dict]] = defaultdict(list)
    for i, r in enumerate(repos):
        groups[assign[i]].append(r)

    clusters = []
    for ci in range(k):
        items = groups.get(ci, [])
        if not items:
            continue
        items_sorted = sorted(items, key=lambda x: int(x.get("stars") or 0), reverse=True)
        # 簇主题词: 出现最多的 function_tags / category
        tag_counter: Counter = Counter()
        cat_counter: Counter = Counter()
        for r in items:
            for t in (r.get("function_tags") or []):
                tag_counter[str(t)] += 1
            if r.get("category"):
                cat_counter[str(r.get("category"))] += 1
        clusters.append({
            "cluster_id": ci,
            "size": len(items),
            "top_tags": [t for t, _ in tag_counter.most_common(5)],
            "top_categories": [c for c, _ in cat_counter.most_common(3)],
            "total_stars": sum(int(r.get("stars") or 0) for r in items),
            "repos": [{
                "full_name": r.get("full_name"),
                "stars": r.get("stars"),
                "category": r.get("category"),
                "function_tags": r.get("function_tags"),
                "function_summary": r.get("function_summary"),
            } for r in items_sorted[:10]],
        })
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return {
        "mode": "kmeans",
        "k": k,
        "clusters": clusters,
        "summary": {"total_repos": len(repos), "num_clusters": len(clusters)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="储备库能力聚类")
    parser.add_argument("--by-tags", action="store_true", help="按功能标签聚类 (默认)")
    parser.add_argument("--kmeans", action="store_true", help="向量 K-means 聚类")
    parser.add_argument("--k", type=int, default=6, help="K-means 簇数 (默认 6)")
    parser.add_argument("--snapshot", type=str, default=None, help="对快照/入库结果聚类")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repos = load_repos(args.snapshot, limit=args.limit)
    print(f"[cluster] loaded {len(repos)} repos")
    if not repos:
        print("(空库)")
        return 1

    if args.kmeans:
        result = kmeans(repos, k=args.k)
    else:
        result = cluster_by_tags(repos)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"== 能力簇 ({result['mode']}) ==")
        for c in result["clusters"][:20]:
            if args.kmeans:
                print(f"簇#{c['cluster_id']}: {c['size']} 项目 | tags={c['top_tags']} | stars={c['total_stars']}")
            else:
                print(f"[{c['tag']}]: {c['count']} 项目 | stars={c['total_stars']}")
            for r in c["repos"][:3]:
                print(f"    - {r['full_name']} ⭐{r['stars']} [{r.get('category_decision', '-')}] {r.get('function_summary', '')[:60]}")
        print("summary:", json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
