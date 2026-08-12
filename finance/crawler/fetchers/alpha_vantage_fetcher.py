"""finance/crawler/fetchers/alpha_vantage_fetcher.py —— Alpha Vantage 全球行情渠道。

需要 API key (params.api_key 或环境变量 ALPHA_VANTAGE_API_KEY); 无 key 降级 demo。
"""

from __future__ import annotations

import os

from finance.crawler.base import CrawlerBase


class AlphaVantageCrawler(CrawlerBase):
    def parse(self, resp: dict) -> list[dict]:
        try:
            data = self.parse_json(resp)
        except Exception:
            return []
        rows = []
        series = None
        for k, v in (data or {}).items():
            if isinstance(v, dict) and ("Time Series" in k or "Daily" in k or "Weekly" in k):
                series = v
        if not series:
            return rows
        for ts, vals in series.items():
            row = {"date": ts}
            for ck, cv in vals.items():
                key = ck.split(" ")[-1].lower()  # "1. open" -> "open"
                row[key] = cv
            rows.append(row)
        return rows


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    inst_id = payload["instrument_id"]
    params = payload["params"]
    api_key = params.get("api_key") or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return _demo(payload, "无 ALPHA_VANTAGE_API_KEY, 降级 demo")
    symbol = params.get("symbol") or inst_id.split(".")[-1]
    function = params.get("function", "TIME_SERIES_DAILY")
    url = (f"https://www.alphavantage.co/query?function={function}"
           f"&symbol={symbol}&apikey={api_key}&outputsize=compact")
    crawler = AlphaVantageCrawler(channel_id=payload["channel_id"],
                                  params={**params, "url": url, "request_interval": 0.5})
    rows = crawler.run()
    if not rows or rows[0].get("_error"):
        return _demo(payload, f"alpha_vantage 获取失败: {rows[0].get('_error') if rows else '空'}")
    return {"ok": True, "raw_rows": rows, "demo": False, "detail": {"symbol": symbol}}


def _demo(payload: dict, reason: str) -> dict:
    import hashlib
    inst_id = payload["instrument_id"]
    seed = int(hashlib.md5(inst_id.encode()).hexdigest()[:8], 16)
    base = 100 + (seed % 9000)
    rows = []
    for i in range(30):
        rows.append({
            "date": f"2026-08-{(i % 28) + 1:02d}",
            "open": round(base + i * 0.9, 4), "high": round(base + i * 0.9 + 1.0, 4),
            "low": round(base + i * 0.9 - 1.0, 4), "close": round(base + i * 0.9 + 0.1, 4),
            "volume": 1000 + (seed % 9000),
        })
    return {"ok": True, "raw_rows": rows, "demo": True,
            "detail": {"reason": reason, "note": "demo 数据"}}
