"""finance/fetchers/rss_fetcher.py —— RSS 聚合适配器 (财经舆论/新闻)。

覆盖: 新华/东方财富/路透/CNBC 等 RSS 源聚合财经舆论。

依赖: pip install feedparser (或标准库 xml.etree 降级解析)。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

# 品种 -> RSS 源列表
RSS_FEEDS = {
    "SENTIMENT.CN.NEWS": [
        "http://www.xinhuanet.com/fortune/index.xml",
        "https://finance.eastmoney.com/rss/gn.xml",
    ],
    "SENTIMENT.GLOBAL.NEWS": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ],
    "SENTIMENT.CRYPTO.FEAR": [],
    "default": [],
}


def fetch(payload: dict) -> dict:
    iid = payload.get("instrument_id", "")
    feeds = RSS_FEEDS.get(iid, RSS_FEEDS.get("default", []))
    rows = []
    for url in feeds:
        rows.extend(_parse_feed(url))
    return {"ok": True, "source": "rss_news", "demo": False,
            "instrument_id": iid, "feeds": feeds,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": {"kind": "news", "rows": rows[:100]}}


def _parse_feed(url: str) -> list[dict]:
    try:
        import feedparser
        parsed = feedparser.parse(url)
        out = []
        for e in parsed.entries[:30]:
            out.append({
                "title": getattr(e, "title", ""),
                "link": getattr(e, "link", ""),
                "published": getattr(e, "published", ""),
                "summary": (getattr(e, "summary", "") or "")[:300],
            })
        return out
    except ImportError:
        # 标准库 xml.etree 解析 RSS (零依赖降级)
        return _parse_feed_stdlib(url)


def _parse_feed_stdlib(url: str) -> list[dict]:
    import urllib.request
    import xml.etree.ElementTree as ET
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            root = ET.fromstring(resp.read())
        out = []
        for item in root.iter("item"):
            title = item.findtext("title", "") or ""
            link = item.findtext("link", "") or ""
            pub = item.findtext("pubDate", "") or ""
            desc = item.findtext("description", "") or ""
            out.append({"title": title, "link": link, "published": pub, "summary": desc[:300]})
            if len(out) >= 30:
                break
        return out
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description="RSS 舆论适配器")
    ap.add_argument("--instrument", required=True, default="SENTIMENT.CN.NEWS")
    args = ap.parse_args()
    payload = {"instrument_id": args.instrument}
    print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
