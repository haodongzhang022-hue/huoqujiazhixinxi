"""finance/crawler/fetchers/rss_fetcher.py —— RSS 舆论/新闻渠道获取脚本。

从 params 表读取 RSS 源列表, 通用引擎抓取 -> 原始行 (title/link/pubDate/description)。
"""

from __future__ import annotations

from finance.crawler.base import CrawlerBase


class RssCrawler(CrawlerBase):
    """RSS 抓取器 (标准库 xml.etree 解析)。"""

    def parse(self, resp: dict) -> list[dict]:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(resp["text"])
        except Exception:
            return []
        rows = []
        for item in root.iter("item"):
            def f(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            rows.append({
                "title": f("title"), "link": f("link"),
                "pubDate": f("pubDate"), "description": f("description")[:500],
            })
        return rows


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    params = payload["params"]
    feeds = params.get("feeds") or ch.get("source") or []
    if isinstance(feeds, str):
        feeds = [feeds]
    if not feeds:
        return {"ok": False, "error": "未配置 feeds (params.feeds 或 channels.source)",
                "raw_rows": [], "demo": False}
    crawler = RssCrawler(channel_id=payload["channel_id"],
                         params={**params, "request_interval": params.get("request_interval", 0.5)})
    all_rows = []
    for url in feeds:
        resp = crawler.http_get(url)
        if resp.get("status") == 200 and not resp.get("error"):
            try:
                all_rows.extend(crawler.parse(resp))
            except Exception:
                pass
    return {"ok": True, "raw_rows": all_rows, "demo": False, "detail": {"feeds": feeds}}
