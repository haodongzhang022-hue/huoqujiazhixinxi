"""finance/registry.py —— 获取器注册表 (Data Fetcher Registry)。

对齐 Issue #6: "索引到目标后, 除了数据, 可能还匹配到了获取信息的脚本, 然后可以触发获取信息"

职责:
  - 数据源脚本 (finance/fetchers/*_fetcher.py) -> 可调用适配器 (动态导入 module)
  - 每个适配器返回统一结构: {ok, source, instrument, fetched_at, data}
  - 提供 fetch_instrument(): 品种 + 数据源 + 参数 -> 触发获取 -> 落盘缓存
  - 缺失依赖 (如未安装 akshare) 时自动降级 demo 模式 (本地生成模拟数据), 保证框架可运行
  - 注册表可扩展: 在 config/finance/catalog.json 新增 source 并实现同名 fetcher 模块即可

用法:
  python -m finance.registry --list
  python -m finance.registry --fetch CN.RB --source akshare --time-level 1d
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from finance.catalog import load_catalog, Catalog

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_registered() -> list[dict]:
    cat = load_catalog()
    out = []
    for s in cat.sources:
        out.append({
            "id": s["id"], "name": s["name"], "type": s["type"],
            "module": s.get("module"), "script": s.get("script"),
            "registered": _module_available(s.get("module")),
        })
    return out


def _module_available(module: str | None) -> bool:
    if not module:
        return False
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


def load_fetcher(source_id: str, catalog: Catalog | None = None):
    """加载数据源获取适配器 (返回 (fetcher_callable, source_info) 或 (None, None))。

    fetcher_callable(instrument: dict, **kwargs) -> dict
    """
    catalog = catalog or load_catalog()
    src = catalog.get(source_id)
    if not src:
        return None, None
    module_name = src.get("module")
    if module_name:
        try:
            mod = importlib.import_module(module_name)
            fn = getattr(mod, "fetch", None)
            if callable(fn):
                return fn, src
        except Exception as e:
            print(f"[registry] 加载 {module_name} 失败: {e}", file=sys.stderr)
    return None, src


def fetch_instrument(instrument: dict, source: str, time_level: str | None = None,
                     trade_type: str | None = None, force_demo: bool = False, **extra) -> dict:
    """触发获取: 品种 + 数据源 -> 适配器 -> 落盘缓存。

    优先真实适配器; 适配器缺失/失败/force_demo 时降级 demo (本地模拟, 框架可离线运行)。
    """
    cat = load_catalog()
    fn, src = load_fetcher(source, cat)
    payload = {
        "instrument": instrument,
        "instrument_id": instrument.get("id", ""),
        "symbol": instrument.get("symbol", ""),
        "name": instrument.get("name", ""),
        "data_class": instrument.get("data_class", ""),
        "exchange": instrument.get("exchange", ""),
        "time_level": time_level,
        "trade_type": trade_type,
        **extra,
    }
    if fn is not None and not force_demo:
        try:
            result = fn(payload)
            result.setdefault("ok", True)
            result.setdefault("source", source)
            result.setdefault("fetched_at", _now())
            _save_cache(source, instrument, time_level, trade_type, result)
            return result
        except Exception as e:
            print(f"[registry] {source} 获取失败: {e} -> 降级 demo", file=sys.stderr)
    # demo 降级
    result = _demo_fetch(payload, source)
    _save_cache(source, instrument, time_level, trade_type, result)
    return result


def _demo_fetch(payload: dict, source: str) -> dict:
    """演示模式: 本地确定性生成模拟数据 (框架离线可运行, 不联网不依赖外部库)。"""
    import hashlib
    seed = hashlib.md5((source + payload["instrument_id"] + str(payload.get("time_level"))).encode()).hexdigest()
    rnd = int(seed[:8], 16)
    base = 100 + (rnd % 9000)
    rows = []
    tl = payload.get("time_level") or "1d"
    n = {"1m": 24, "5m": 24, "15m": 12, "30m": 12, "1h": 24, "4h": 12, "1d": 30, "1w": 12, "1M": 12}.get(tl, 30)
    for i in range(n):
        drift = ((rnd >> (i % 12)) & 0xF) / 100.0 - 0.05
        rows.append({
            "time": f"2026-08-{(i % 28) + 1:02d}T00:00:00Z",
            "open": round(base + i * 1.3, 2),
            "high": round(base + i * 1.3 + 2.0, 2),
            "low": round(base + i * 1.3 - 2.0, 2),
            "close": round(base + i * 1.3 + drift, 2),
            "volume": 1000 + (rnd % 9000),
        })
    return {
        "ok": True,
        "source": source,
        "demo": True,
        "instrument_id": payload["instrument_id"],
        "name": payload.get("name", ""),
        "time_level": tl,
        "trade_type": payload.get("trade_type"),
        "fetched_at": _now(),
        "data": {"kind": "ohlcv", "rows": rows, "note": "demo 模拟数据, 接入真实 API 后自动替换"},
    }


def _save_cache(source: str, instrument: dict, time_level: str | None,
                trade_type: str | None, result: dict):
    """落盘缓存: finance/data/cache/{source}/{instrument_id}_{time_level}_{trade_type}.json"""
    key = f"{instrument.get('id', 'unknown')}"
    if time_level:
        key += f"_{time_level}"
    if trade_type:
        key += f"_{trade_type}"
    d = CACHE_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{key}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)


def main():
    ap = argparse.ArgumentParser(description="获取器注册表")
    ap.add_argument("--list", action="store_true", help="列出注册的获取器")
    ap.add_argument("--fetch", metavar="INSTRUMENT", help="触发获取品种")
    ap.add_argument("--source", help="数据源 id")
    ap.add_argument("--time-level", help="时间级别")
    ap.add_argument("--trade-type", help="交易类型")
    ap.add_argument("--force-demo", action="store_true", help="强制 demo 模式")
    args = ap.parse_args()

    if args.list:
        for r in list_registered():
            print(f"  {r['id']:<16} {r['name']}  module={r['module']}  registered={'✓' if r['registered'] else '✗(将降级demo)'}")
        return
    if args.fetch:
        from finance.taxonomy import load_taxonomy
        tax = load_taxonomy()
        inst = tax.resolve_instrument(args.fetch)
        if not inst:
            print(f"未找到品种: {args.fetch}", file=sys.stderr)
            sys.exit(1)
        result = fetch_instrument(inst, source=args.source or "manual",
                                  time_level=args.time_level, trade_type=args.trade_type,
                                  force_demo=args.force_demo)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
