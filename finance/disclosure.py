"""finance/disclosure.py —— 渐进式披露 (Progressive Disclosure)。

对齐 Issue #6: "通过这样的索引, 实现对数据的聚类、分类和渐进式披露"。

三级披露 (从轻到重, 按需取用):
  L0 index   索引级   : 品种/数据源/文件列表 轻量摘要 (不触发任何获取)
  L1 meta    元数据级 : 缓存元信息/已获取状态/时间范围/数据规模 (读取本地缓存索引)
  L2 full    全量级   : 完整数据 (触发获取脚本, 或读取已缓存全量数据)

原则:
  - 渐进: 先 index 定位 -> 再 meta 确认 -> 最后 full 才花成本获取/读取全量
  - 惰性: full 级不预先拉取, 只在用户显式触发时执行
  - 缓存: 已获取的数据落地 finance/data/cache/, meta 级可离线回答

用法:
  python -m finance.disclosure --instrument CN.RB --level index
  python -m finance.disclosure --instrument CN.RB --level meta
  python -m finance.disclosure --instrument CN.RB --level full --source akshare --time-level 1d
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from finance.taxonomy import load_taxonomy
from finance.catalog import load_catalog

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_cache_files() -> list[dict]:
    """finance/data/cache/ 下的缓存文件索引。"""
    files = []
    if CACHE_DIR.exists():
        for p in sorted(CACHE_DIR.rglob("*")):
            if p.is_file() and p.suffix == ".json":
                st = p.stat()
                files.append({
                    "path": str(p.relative_to(CACHE_DIR)),
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                })
    return files


def index_level(instrument: str | None = None) -> dict:
    """L0 索引级: 品种/数据源/缓存文件的轻量索引 (不触发获取)。"""
    tax = load_taxonomy()
    cat = load_catalog()
    result = {
        "level": "index",
        "generated_at": _now(),
        "summary": {
            "data_classes": list(tax.data_classes.keys()),
            "regions": list(tax.regions.keys()),
            "exchanges": list(tax.exchanges.keys()),
            "time_levels": list(tax.time_levels.keys()),
            "trade_types": list(tax.trade_types.keys()),
            "instruments": len(tax.instruments),
            "sources": len(cat.sources),
            "cached_files": len(list_cache_files()),
        },
    }
    if instrument:
        inst = tax.resolve_instrument(instrument)
        result["instrument"] = inst
        result["available_sources"] = [
            {"id": s["id"], "name": s["name"], "script": s["script"]}
            for s in cat.sources_for_instrument(inst or {})
        ]
    return result


def meta_level(instrument: str) -> dict:
    """L1 元数据级: 品种索引卡 + 可用数据源 + 缓存状态 (读取本地, 不触发获取)。"""
    tax = load_taxonomy()
    cat = load_catalog()
    inst = tax.resolve_instrument(instrument)
    if not inst:
        return {"level": "meta", "error": f"未找到品种: {instrument}"}
    iid = inst["id"]
    card = tax.describe_instrument(iid)
    # 缓存状态: 按 id / symbol 匹配
    cache_files = [f for f in list_cache_files() if iid.split(".")[-1].lower() in f["path"].lower()
                   or iid.lower() in f["path"].lower()]
    sources = []
    for s in cat.sources_for_instrument(inst):
        sources.append({
            "id": s["id"], "name": s["name"], "type": s["type"], "status": s.get("status"),
            "script": s["script"], "command": s["command"],
            "schedule": s.get("schedule", {}), "disclosure": s.get("disclosure", {}),
            "requires": s.get("requires", {}),
        })
    return {
        "level": "meta",
        "generated_at": _now(),
        "instrument_card": card,
        "sources": sources,
        "cache": {"has_cache": bool(cache_files), "files": cache_files},
    }


def full_level(instrument: str, source: str | None = None, time_level: str | None = None,
               trade_type: str | None = None, refresh: bool = False, **extra) -> dict:
    """L2 全量级: 触发获取脚本拉取完整数据 (或读缓存)。"""
    tax = load_taxonomy()
    cat = load_catalog()
    inst = tax.resolve_instrument(instrument)
    if not inst:
        return {"level": "full", "error": f"未找到品种: {instrument}"}

    sources = cat.sources_for_instrument(inst)
    if source:
        sources = [s for s in sources if s["id"] == source]
    if not sources:
        return {"level": "full", "error": f"品种 {instrument} 没有可用数据源",
                "instrument": inst}

    # 优先读缓存 (不 refresh)
    cache_key = f"{inst['id']}_{time_level or 'default'}_{trade_type or ''}".strip("_")
    cached = _read_cache(source or sources[0]["id"], cache_key)
    if cached is not None and not refresh:
        return {"level": "full", "from_cache": True, "instrument": inst,
                "source": source or sources[0]["id"], "data": cached}

    # 触发获取: 通过 registry 调用脚本适配器
    from finance.registry import fetch_instrument
    result = fetch_instrument(inst, source=source or sources[0]["id"],
                              time_level=time_level, trade_type=trade_type, **extra)
    return {"level": "full", "from_cache": False, "instrument": inst,
            "source": source or sources[0]["id"], "result": result}


def _read_cache(source_id: str, key: str):
    """读取缓存文件 (带过期判断由 scheduler/调用方处理)。"""
    base = CACHE_DIR / source_id
    if not base.exists():
        return None
    # 尝试精确 key / 子串匹配
    candidates = list(base.rglob("*.json"))
    exact = base / f"{key}.json"
    if exact.exists():
        try:
            with open(exact, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    # 模糊匹配: 包含 key 的任意片段
    parts = [p for p in key.split("_") if p]
    for p in candidates:
        name = p.stem.lower()
        if all(part.lower() in name for part in parts):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None


def main():
    ap = argparse.ArgumentParser(description="渐进式披露 (index -> meta -> full)")
    ap.add_argument("--instrument", required=True, help="品种 id/代码/名称")
    ap.add_argument("--level", choices=["index", "meta", "full"], default="meta")
    ap.add_argument("--source", help="数据源 id (full 级)")
    ap.add_argument("--time-level", help="时间级别 (full 级)")
    ap.add_argument("--trade-type", help="交易类型 (full 级)")
    ap.add_argument("--refresh", action="store_true", help="full 级强制重新获取")
    args = ap.parse_args()

    if args.level == "index":
        print(json.dumps(index_level(args.instrument), ensure_ascii=False, indent=2))
    elif args.level == "meta":
        print(json.dumps(meta_level(args.instrument), ensure_ascii=False, indent=2))
    else:
        r = full_level(args.instrument, source=args.source, time_level=args.time_level,
                       trade_type=args.trade_type, refresh=args.refresh)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
