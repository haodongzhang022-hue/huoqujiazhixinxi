"""finance/fetchers/yfinance_fetcher.py —— Yahoo Finance 数据源适配器 (全球股票/ETF/外汇/期货)。

依赖: pip install yfinance pandas
未安装时抛 ImportError -> 由 finance/registry.py 降级 demo。
"""

from __future__ import annotations

import argparse
import json
import sys


def _yahoo_symbol(instrument: dict, trade_type: str | None = None) -> str:
    """品种 -> Yahoo 符号映射。"""
    iid = instrument.get("id", "")
    symbol = instrument.get("symbol", "")
    exchange = instrument.get("exchange", "")
    if iid.startswith("US."):
        return symbol
    if iid.startswith("HK."):
        return f"{symbol}.HK"
    if iid.startswith("JP."):
        return f"{symbol}.T"
    if iid.startswith("KR."):
        return f"{symbol}.KS"
    if iid.startswith("FX."):
        return f"{symbol}=X"
    return symbol


def fetch(payload: dict) -> dict:
    import yfinance as yf  # noqa: F401

    inst = payload.get("instrument") or {}
    ysym = _yahoo_symbol(inst, payload.get("trade_type"))
    tl = payload.get("time_level", "1d")
    period_map = {"1d": "1y", "1w": "5y", "1M": "max", "1m": "5d", "5m": "1mo", "1h": "1mo"}
    period = period_map.get(tl, "1y")
    interval = tl if tl in ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M") else "1d"

    ticker = yf.Ticker(ysym)
    df = ticker.history(period=period, interval=interval)
    result = {"ok": True, "source": "yfinance", "demo": False,
              "instrument_id": payload.get("instrument_id", ""),
              "yahoo_symbol": ysym, "time_level": tl,
              "fetched_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    if df is not None and not df.empty:
        df = df.reset_index()
        result["data"] = {"kind": "ohlcv", "rows": df.tail(500).to_dict(orient="records")}
    else:
        raise RuntimeError(f"yfinance 无数据: {ysym}")
    return result


def main():
    ap = argparse.ArgumentParser(description="Yahoo Finance 适配器")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--time-level", default="1d")
    ap.add_argument("--trade-type")
    args = ap.parse_args()
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument": inst, "instrument_id": inst["id"],
               "time_level": args.time_level, "trade_type": args.trade_type}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except ImportError as e:
        print(f"[yfinance] 依赖未安装: {e}", file=sys.stderr)
        print("[yfinance] 提示: pip install yfinance ; 或通过 finance.registry 触发 demo 降级", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
