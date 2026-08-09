"""检索服务 (search.py) —— 全文 / 向量 / 混合检索储备库。

对应调研报告 §5.3 的复现形式:
  - FTS:  "我需要一个能压缩 LLM token 的开源库" -> 关键词匹配
  - 向量: 同上描述 -> 语义 Top-K
  - 混合: 两者加权
  - SQL:  按 category / function_tags / stars_delta 过滤

CLI 用法:
  python -m reserve.search "需要 RAG 向量检索能力"
  python -m reserve.search "mcp server" --top 5 --decision reserve
  python -m reserve.search "压缩 token 的开源库" --vector
"""

from __future__ import annotations

import argparse
import json
import sys

from reserve.store import ReserveStore
from reserve.embedding import embed_text


def search(text: str, top_k: int = 10, mode: str = "hybrid",
           decision: str | None = None, store: ReserveStore | None = None) -> list[dict]:
    """检索储备库。

    mode: hybrid (默认) / fts / vector
    decision: action / reserve / partial / ignore 过滤
    """
    store = store or ReserveStore()
    where = None
    if decision:
        where = f"category_decision = '{decision}'"

    if mode == "fts":
        return store.search_fts(text, limit=top_k, where=where)
    if mode == "vector":
        emb = embed_text(text)
        return store.search_vector(emb, limit=top_k, where=where)
    emb = embed_text(text)
    try:
        return store.search_hybrid(text, emb, limit=top_k, where=where)
    except Exception as e:
        print(f"[search] hybrid error (fallback fts): {e}")
        return store.search_fts(text, limit=top_k, where=where)


def format_results(results: list[dict]) -> str:
    if not results:
        return "(无结果)"
    lines = []
    for i, r in enumerate(results, 1):
        tags = r.get("function_tags")
        tags = tags if tags is not None else []
        lines.append(
            f"{i}. {r.get('full_name', '')} ⭐{r.get('stars', 0)} "
            f"[{r.get('category_decision', '-')}]"
        )
        if r.get("function_summary"):
            lines.append(f"   摘要: {r['function_summary']}")
        if len(tags) > 0:
            lines.append(f"   功能: {', '.join(str(t) for t in tags)}")
        if r.get("use_case"):
            lines.append(f"   场景: {r['use_case']}")
        if r.get("decision_reason"):
            lines.append(f"   判断: {r['decision_reason']}")
        if "_distance" in r:
            lines.append(f"   相似度: {round(float(r['_distance']), 4)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="储备库检索")
    parser.add_argument("query", help="检索描述 (如: 需要 RAG 向量检索能力)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--mode", choices=["hybrid", "fts", "vector"], default="hybrid")
    parser.add_argument("--decision", choices=["action", "reserve", "partial", "ignore"], default=None)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    results = search(args.query, top_k=args.top, mode=args.mode, decision=args.decision)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=_json_default))
    else:
        print(format_results(results))
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
