"""finance/fetchers/akshare_fetcher.py —— AKShare 数据源适配器 (中国及全球行情)。

覆盖: A股/港股/美股行情, 国内期货, 大宗现货, 基金净值, 中国宏观指标, 汇率。

依赖: pip install akshare pandas
未安装时抛 ImportError -> 由 finance/registry.py 降级 demo。

用法:
  python -m finance.fetchers.akshare_fetcher --instrument CN.RB --time-level 1d
"""

from __future__ import annotations

import argparse
import json
import sys


def fetch(payload: dict) -> dict:
    """AKShare 获取入口 (registry 调用)。payload: {instrument_id, symbol, data_class, exchange, time_level, trade_type, ...}"""
    import akshare as ak  # noqa: F401  依赖检查

    inst_id = payload.get("instrument_id", "")
    symbol = payload.get("symbol", "")
    data_class = payload.get("data_class", "")
    exchange = payload.get("exchange", "")
    tl = payload.get("time_level", "1d")

    # 按数据类别路由到不同 AKShare 接口 (每个分类不同的获取方式)
    result = {"ok": True, "source": "akshare", "demo": False,
              "instrument_id": inst_id, "time_level": tl,
              "fetched_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}

    if data_class == "futures" and exchange in ("SHFE", "DCE", "CZCE", "INE", "GFEX"):
        df = ak.futures_zh_daily_sina(symbol=symbol)
        result["data"] = {"kind": "ohlcv", "rows": df.tail(120).to_dict(orient="records")}
    elif data_class == "stock" and exchange in ("SSE", "SZSE", "BSE"):
        df = ak.stock_zh_a_hist(symbol=symbol, period=tl, adjust="qfq")
        result["data"] = {"kind": "ohlcv", "rows": df.tail(250).to_dict(orient="records")}
    elif data_class == "stock" and exchange == "HKEX":
        df = ak.stock_hk_hist(symbol=symbol)
        result["data"] = {"kind": "ohlcv", "rows": df.tail(250).to_dict(orient="records")}
    elif data_class == "fund":
        df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
        result["data"] = {"kind": "net_value", "rows": df.tail(250).to_dict(orient="records")}
    elif data_class == "macro":
        df = ak.macro_china_gdp() if "GDP" in inst_id.upper() else ak.macro_china_cpi()
        result["data"] = {"kind": "macro_series", "rows": df.tail(120).to_dict(orient="records")}
    else:
        raise NotImplementedError(f"akshare 暂未覆盖: {data_class}@{exchange}")

    return result


def main():
    ap = argparse.ArgumentParser(description="AKShare 适配器")
    ap.add_argument("--instrument", required=True, help="品种 id (如 CN.RB)")
    ap.add_argument("--time-level", default="1d")
    ap.add_argument("--trade-type")
    args = ap.parse_args()

    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument_id": inst["id"], "time_level": args.time_level,
               "trade_type": args.trade_type}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except ImportError as e:
        print(f"[akshare] 依赖未安装或接口不可用: {e}", file=sys.stderr)
        print("[akshare] 提示: pip install akshare ; 或通过 finance.registry 触发 demo 降级", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
