"""finance/fetchers/alpha_vantage_fetcher.py —— Alpha Vantage 数据源适配器 (全球股票/外汇/宏观/加密)。

依赖: 环境变量 ALPHA_VANTAGE_API_KEY (免费注册 https://www.alphavantage.co/support/#api-key)
      urllib 标准库直连。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

AV_BASE = "https://www.alphavantage.co/query"
AV_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")


def fetch(payload: dict) -> dict:
    if not AV_KEY:
        raise RuntimeError("缺少 ALPHA_VANTAGE_API_KEY 环境变量 (https://www.alphavantage.co/support/#api-key)")
    inst = payload.get("instrument") or {}
    symbol = inst.get("symbol", "")
    tl = payload.get("time_level", "1d")
    data_class = payload.get("data_class", "stock")

    if data_class in ("stock", "fund", "etf"):
        fn = "TIME_SERIES_DAILY"
        key = "Time Series (Daily)"
        if tl in ("1m", "5m", "15m", "30m", "1h"):
            fn = "TIME_SERIES_INTRADAY"
            key = f"Time Series ({tl})"
            params = {"function": fn, "symbol": symbol, "interval": tl, "outputsize": "compact", "apikey": AV_KEY}
        else:
            params = {"function": fn, "symbol": symbol, "outputsize": "compact", "apikey": AV_KEY}
    elif data_class == "forex":
        params = {"function": "FX_DAILY", "from_symbol": symbol[:3], "to_symbol": symbol[3:], "outputsize": "compact", "apikey": AV_KEY}
        key = "Time Series FX (Daily)"
    else:
        raise NotImplementedError(f"alpha_vantage 暂未覆盖: {data_class}")

    url = f"{AV_BASE}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if key not in data:
        raise RuntimeError(f"alpha_vantage 返回异常: {list(data.keys())}")
    rows = [{"time": t, **v} for t, v in data[key].items()]
    return {"ok": True, "source": "alpha_vantage", "demo": False,
            "instrument_id": payload.get("instrument_id", ""),
            "symbol": symbol, "time_level": tl,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": {"kind": "ohlcv", "rows": rows}}


def main():
    ap = argparse.ArgumentParser(description="Alpha Vantage 适配器")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--time-level", default="1d")
    args = ap.parse_args()
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument": inst, "instrument_id": inst["id"], "time_level": args.time_level}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[alpha_vantage] 获取失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
