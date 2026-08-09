"""finance/crawler/fetchers/yfinance_fetcher.py —— Yahoo Finance 渠道获取脚本。

全球股票/ETF/外汇/期货行情 (python 库 yfinance)。失败自动降级 demo。
"""

from __future__ import annotations


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    inst_id = payload["instrument_id"]
    params = payload["params"]
    tl = payload.get("time_level") or params.get("time_level") or "1d"

    try:
        import yfinance as yf
    except ImportError:
        return _demo(payload, "依赖缺失: pip install yfinance")

    symbol = params.get("symbol") or _default_symbol(inst_id)
    period = {"1d": "1mo", "1w": "6mo", "1M": "2y"}.get(tl, "1mo")
    interval = {"1d": "1d", "1w": "1wk", "1M": "1mo"}.get(tl, "1d")
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df is None or len(df) == 0:
            return _demo(payload, "yfinance 返回空")
        df = df.reset_index()
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "date": str(r.get("Date", "")),
                "open": _f(r.get("Open")), "high": _f(r.get("High")),
                "low": _f(r.get("Low")), "close": _f(r.get("Close")),
                "volume": _f(r.get("Volume")),
            })
        return {"ok": True, "raw_rows": rows, "demo": False,
                "detail": {"symbol": symbol, "interval": interval}}
    except Exception as e:  # noqa: BLE001
        return _demo(payload, f"yfinance 获取失败: {e}")


def _f(v):
    try:
        if v is None or (hasattr(v, "isna") and v.isna()):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _default_symbol(inst_id: str) -> str:
    m = {"US.AAPL": "AAPL", "US.SPY": "SPY", "JP.7203": "7203.T", "KR.005930": "005930.KS",
         "FX.USDCNY": "CNY=X", "FX.EURUSD": "EURUSD=X", "FX.USDJPY": "JPY=X",
         "US.CL": "CL=F", "US.GC": "GC=F"}
    return m.get(inst_id, inst_id)


def _demo(payload: dict, reason: str) -> dict:
    import hashlib
    inst_id = payload["instrument_id"]
    seed = int(hashlib.md5(inst_id.encode()).hexdigest()[:8], 16)
    base = 100 + (seed % 9000)
    rows = []
    for i in range(30):
        rows.append({
            "date": f"2026-08-{(i % 28) + 1:02d}",
            "open": round(base + i * 1.1, 2), "high": round(base + i * 1.1 + 1.5, 2),
            "low": round(base + i * 1.1 - 1.5, 2), "close": round(base + i * 1.1 + 0.3, 2),
            "volume": 1000 + (seed % 9000),
        })
    return {"ok": True, "raw_rows": rows, "demo": True,
            "detail": {"reason": reason, "note": "demo 数据"}}
