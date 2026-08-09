"""finance/fetchers/finnhub_fetcher.py —— Finnhub 数据源适配器 (全球行情+新闻+情绪)。

覆盖: 财经新闻流 / 个股新闻 / 实时报价 (股票/外汇/加密)。

依赖: 环境变量 FINNHUB_API_KEY (免费注册 https://finnhub.io), urllib 标准库直连。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")


def _get(path: str, params: dict) -> dict:
    if not FINNHUB_KEY:
        raise RuntimeError("缺少 FINNHUB_API_KEY 环境变量 (https://finnhub.io)")
    params = {**params, "token": FINNHUB_KEY}
    url = f"{FINNHUB_BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(payload: dict) -> dict:
    inst = payload.get("instrument") or {}
    iid = payload.get("instrument_id", "")
    if "NEWS" in iid.upper():
        # 新闻流: 全球/个股
        if iid.startswith("SENTIMENT.CN"):
            params = {"category": "general"}
            rows = _get("news", params).get("data", [])
        else:
            symbol = inst.get("symbol", "")
            if symbol and "NEWS" not in symbol.upper():
                rows = _get("company-news", {"symbol": symbol, "from": "2026-01-01", "to": "2026-12-31"}).get("data", [])
            else:
                rows = _get("news", {"category": "general"}).get("data", [])
        return {"ok": True, "source": "finnhub", "demo": False,
                "instrument_id": iid,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "data": {"kind": "news", "rows": rows}}
    # 报价
    symbol = inst.get("symbol", "")
    quote = _get("quote", {"symbol": symbol})
    return {"ok": True, "source": "finnhub", "demo": False,
            "instrument_id": iid, "symbol": symbol,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": {"kind": "quote", "quote": quote}}


def main():
    ap = argparse.ArgumentParser(description="Finnhub 新闻/报价适配器")
    ap.add_argument("--instrument", required=True)
    args = ap.parse_args()
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument": inst, "instrument_id": inst["id"]}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[finnhub] 获取失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
