"""finance/crawler/fetchers/finnhub_fetcher.py —— Finnhub 新闻/情绪渠道。

全球财经新闻 + 市场情绪 (需要 API key; 无 key 降级 demo)。
"""

from __future__ import annotations

from finance.crawler.base import CrawlerBase


class FinnhubCrawler(CrawlerBase):
    def parse(self, resp: dict) -> list[dict]:
        try:
            data = self.parse_json(resp)
        except Exception:
            return []
        out = []
        for n in (data or {}).get("data") or []:
            out.append({
                "title": n.get("headline", ""),
                "link": n.get("url", ""),
                "content": (n.get("summary", "") or "")[:500],
                "pubDate": _fmt_ts(n.get("datetime")),
                "source": n.get("source", ""),
            })
        return out


def _fmt_ts(ts):
    if not ts:
        return ""
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    params = payload["params"]
    api_key = params.get("api_key") or ""
    if not api_key:
        return _demo(payload, "无 FINNHUB_API_KEY, 降级 demo")
    url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
    crawler = FinnhubCrawler(channel_id=payload["channel_id"],
                             params={**params, "url": url, "request_interval": 0.3})
    rows = crawler.run()
    if not rows or rows[0].get("_error"):
        return _demo(payload, f"finnhub 获取失败: {rows[0].get('_error') if rows else '空'}")
    return {"ok": True, "raw_rows": rows, "demo": False}


def _demo(payload: dict, reason: str) -> dict:
    return {"ok": True, "raw_rows": [
        {"title": "示例新闻标题 (demo)", "link": "https://example.com/news/1",
         "content": "demo 新闻内容, 接入 FINNHUB_API_KEY 后替换",
         "pubDate": "2026-08-09T00:00:00Z", "source": "demo"},
    ], "demo": True, "detail": {"reason": reason}}
