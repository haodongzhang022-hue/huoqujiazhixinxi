"""finance/fetchers/ccxt_fetcher.py —— CCXT 数据源适配器 (加密货币交易所聚合)。

覆盖: 币安/欧易/Bybit/Coinbase/Upbit 等 100+ 交易所的现货/合约/永续/期权 K线、Ticker、盘口。

依赖: pip install ccxt
未安装时抛 ImportError -> 由 finance/registry.py 降级 demo。
"""

from __future__ import annotations

import argparse
import json
import sys

# 品种 exchange 字段 -> ccxt 交易所 id
CCXT_EXCHANGE = {
    "BINANCE": "binance", "OKX": "okx", "BYBIT": "bybit",
    "COINBASE": "coinbase", "UPBIT": "upbit", "GATE": "gate", "KRAKEN": "kraken",
}


def _ccxt_symbol(instrument: dict, trade_type: str | None = None) -> str:
    symbol = instrument.get("symbol", "")
    if trade_type in ("contract", "perpetual", "option"):
        return f"{symbol}/USDT:USDT"  # 永续/合约统一用 USDT 本位
    return f"{symbol}/USDT"


def fetch(payload: dict) -> dict:
    import ccxt  # noqa: F401

    inst = payload.get("instrument") or {}
    ex_id = CCXT_EXCHANGE.get(inst.get("exchange", ""), "binance")
    symbol = _ccxt_symbol(inst, payload.get("trade_type"))
    tl = payload.get("time_level", "1d")
    timeframe = tl if tl in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w") else "1d"
    limit = payload.get("limit", 300)

    exchange = getattr(ccxt, ex_id)({"enableRateLimit": True})
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    rows = [{"time": exchange.iso8601(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]} for r in ohlcv]
    return {"ok": True, "source": "ccxt", "demo": False,
            "instrument_id": payload.get("instrument_id", ""),
            "exchange_id": ex_id, "ccxt_symbol": symbol, "timeframe": timeframe,
            "fetched_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "data": {"kind": "ohlcv", "rows": rows}}


def main():
    ap = argparse.ArgumentParser(description="CCXT 加密适配器")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--time-level", default="1d")
    ap.add_argument("--trade-type", default="spot")
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
        print(f"[ccxt] 依赖未安装: {e}", file=sys.stderr)
        print("[ccxt] 提示: pip install ccxt ; 或通过 finance.registry 触发 demo 降级", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
