"""finance/crawler/fetchers/akshare_fetcher.py —— AKShare 渠道获取脚本 (python 库)。

与旧版 finance/fetchers/akshare_fetcher.py 对齐, 但走 LanceDB 渠道定义:
  - 品种的映射参数 (symbol 映射 / AKShare 接口选择) 来自 params 表 (scope=instrument);
  - 获取失败自动降级 demo 数据 (保证全链路可运行)。
"""

from __future__ import annotations

from finance.crawler.base import now_utc


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    inst_id = payload["instrument_id"]
    params = payload["params"]
    tl = payload.get("time_level") or params.get("time_level") or "1d"

    try:
        import akshare as ak  # noqa: F401
        import pandas as pd  # noqa: F401
    except ImportError:
        return _demo(payload, "依赖缺失: pip install akshare")

    symbol = params.get("symbol") or _default_symbol(inst_id)
    data_class = params.get("data_class") or ""
    exchange = params.get("exchange") or ""
    method = params.get("ak_method") or _default_method(data_class, exchange)

    try:
        if method == "stock_zh_a_hist":
            df = ak.stock_zh_a_hist(symbol=symbol, period=tl, adjust="qfq")
            rows = _df_rows(df)
        elif method == "futures_zh_daily_sina":
            df = ak.futures_zh_daily_sina(symbol=symbol)
            rows = _df_rows(df)
        elif method == "macro_china_gdp":
            df = ak.macro_china_gdp()
            rows = _df_rows(df)
        elif method == "macro_china_cpi":
            df = ak.macro_china_cpi()
            rows = _df_rows(df)
        else:
            return _demo(payload, f"akshare 未覆盖 method={method}")
        return {"ok": True, "raw_rows": rows, "demo": False,
                "detail": {"method": method, "symbol": symbol}}
    except Exception as e:  # noqa: BLE001
        return _demo(payload, f"akshare 获取失败: {e}")


def _df_rows(df):
    import pandas as pd
    if df is None or len(df) == 0:
        return []
    # 列名中文 -> 拼音/英文标准列, 便于 column_defs 映射
    rename = {
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "成交额": "amount",
        "时间": "date", "指标": "indicator", "数值": "value",
        "季度": "quarter", "今值": "value", "前值": "prev_value",
        "预测值": "forecast", "公布时间": "date",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    return df.tail(250).to_dict(orient="records")


def _default_symbol(inst_id: str) -> str:
    """品种 id -> AKShare symbol (可由 params 表覆盖)。"""
    m = {
        "SH600000": "600000", "SH510300": "510300", "HK00700": "00700",
        "CN.RB": "RB0", "CN.CU": "CU0", "CN.IF": "IF0",
    }
    if inst_id in m:
        return m[inst_id]
    return inst_id.split(".")[-1]


def _default_method(data_class: str, exchange: str) -> str:
    if data_class == "futures":
        return "futures_zh_daily_sina"
    if data_class == "stock":
        return "stock_zh_a_hist"
    if data_class == "macro":
        return "macro_china_gdp"
    return "stock_zh_a_hist"


def _demo(payload: dict, reason: str) -> dict:
    """降级 demo: 生成模拟原始行 (列名用标准列, 映射后直接落库)。"""
    import hashlib
    inst_id = payload["instrument_id"]
    seed = int(hashlib.md5(inst_id.encode()).hexdigest()[:8], 16)
    base = 100 + (seed % 9000)
    rows = []
    for i in range(30):
        rows.append({
            "date": f"2026-08-{(i % 28) + 1:02d}",
            "open": round(base + i * 1.3, 2),
            "high": round(base + i * 1.3 + 2.0, 2),
            "low": round(base + i * 1.3 - 2.0, 2),
            "close": round(base + i * 1.3 + (seed % 7) / 10.0, 2),
            "volume": 1000 + (seed % 9000),
            "amount": 1_000_000 + (seed % 900_000),
        })
    return {"ok": True, "raw_rows": rows, "demo": True,
            "detail": {"reason": reason, "note": "demo 数据, 接入真实 API 自动替换"}}
