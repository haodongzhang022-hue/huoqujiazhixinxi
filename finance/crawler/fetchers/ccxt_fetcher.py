"""finance/crawler/fetchers/ccxt_fetcher.py —— CCXT 加密货币渠道获取脚本。

100+ 交易所统一接口 (python 库 ccxt)。失败自动降级 demo。
"""

from __future__ import annotations


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    inst_id = payload["instrument_id"]
    params = payload["params"]
    tl = payload.get("time_level") or params.get("time_level") or "1d"
    trade_type = payload.get("trade_type") or params.get("trade_type") or "spot"

    try:
        import ccxt
    except ImportError:
        return _demo(payload, "依赖缺失: pip install ccxt")

    exchange_name = params.get("exchange_id") or "binance"
    symbol = params.get("symbol") or _default_symbol(inst_id)
    timeframe = tl
    limit = int(params.get("limit", 120))
    try:
        ex_class = getattr(ccxt, exchange_name)
        ex = ex_class({"enableRateLimit": True, "timeout": 15000})
        if trade_type == "spot":
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        elif trade_type in ("contract", "perpetual"):
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, params={"type": "swap"})
        else:
            ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        rows = []
        for o in ohlcv:
            rows.append({
                "date": _fmt_ts(o[0]), "open": o[1], "high": o[2],
                "low": o[3], "close": o[4], "volume": o[5],
            })
        return {"ok": True, "raw_rows": rows, "demo": False,
                "detail": {"exchange": exchange_name, "symbol": symbol, "timeframe": timeframe}}
    except Exception as e:  # noqa: BLE001
        return _demo(payload, f"ccxt 获取失败: {e}")


def _fmt_ts(ts_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_symbol(inst_id: str) -> str:
    m = {"CRYPTO.BTC": "BTC/USDT", "CRYPTO.ETH": "ETH/USDT", "CRYPTO.SOL": "SOL/USDT"}
    return m.get(inst_id, inst_id)


def _demo(payload: dict, reason: str) -> dict:
    import hashlib
    inst_id = payload["instrument_id"]
    seed = int(hashlib.md5(inst_id.encode()).hexdigest()[:8], 16)
    base = 100 + (seed % 9000)
    rows = []
    for i in range(60):
        rows.append({
            "date": f"2026-08-{(i % 28) + 1:02d}T{(i * 2) % 24:02d}:00:00Z",
            "open": round(base + i * 0.8, 2), "high": round(base + i * 0.8 + 1.2, 2),
            "low": round(base + i * 0.8 - 1.2, 2), "close": round(base + i * 0.8 + 0.2, 2),
            "volume": 100 + (seed % 900),
        })
    return {"ok": True, "raw_rows": rows, "demo": True,
            "detail": {"reason": reason, "note": "demo 数据"}}
