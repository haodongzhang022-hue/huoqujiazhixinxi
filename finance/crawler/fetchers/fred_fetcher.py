"""finance/crawler/fetchers/fred_fetcher.py —— FRED 宏观数据渠道 (美联储经济数据)。

获取方式: https://api.stlouisfed.org/fred/series/observations?series_id=...&api_key=...
失败自动降级 demo。
"""

from __future__ import annotations

from finance.crawler.base import CrawlerBase


class FredCrawler(CrawlerBase):
    """FRED API 抓取器。"""

    def parse(self, resp: dict) -> list[dict]:
        try:
            data = self.parse_json(resp)
        except Exception:
            return []
        obs = (data or {}).get("observations") or []
        rows = []
        for o in obs:
            rows.append({
                "date": o.get("date", ""),
                "value": o.get("value"),
                "series_id": o.get("series_id", ""),
            })
        return rows


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    inst_id = payload["instrument_id"]
    params = payload["params"]
    series_id = params.get("series_id") or _default_series(inst_id)
    api_key = params.get("api_key") or ""
    if not api_key:
        # 无 key: 用 DEMO_KEY 尝试 (FRED 官方允许), 失败降级 demo
        api_key = "DEMO_KEY"
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=1000")
    crawler = FredCrawler(channel_id=payload["channel_id"],
                          params={**params, "url": url, "request_interval": 0.3})
    rows = crawler.run()
    if not rows or rows[0].get("_error"):
        return _demo(payload, f"FRED 获取失败: {rows[0].get('_error') if rows else '空'}",
                     series_id)
    return {"ok": True, "raw_rows": rows, "demo": False, "detail": {"series_id": series_id}}


def _default_series(inst_id: str) -> str:
    m = {"MACRO.US.CPI": "CPIAUCSL", "MACRO.US.FEDRATE": "DFF", "MACRO.US.UNRATE": "UNRATE"}
    return m.get(inst_id, inst_id)


def _demo(payload: dict, reason: str, series_id: str) -> dict:
    import hashlib
    seed = int(hashlib.md5(series_id.encode()).hexdigest()[:8], 16)
    rows = []
    for i in range(60):
        rows.append({
            "date": f"2026-0{(i // 30) + 1}-{(i % 28) + 1:02d}",
            "value": round(50 + (seed % 4000) / 100.0 + i * 0.1, 2),
            "series_id": series_id,
        })
    return {"ok": True, "raw_rows": rows, "demo": True,
            "detail": {"reason": reason, "series_id": series_id, "note": "demo 数据"}}
