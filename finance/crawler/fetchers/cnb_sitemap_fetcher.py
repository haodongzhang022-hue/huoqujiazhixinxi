"""finance/crawler/fetchers/cnb_sitemap_fetcher.py —— CNB 平台站点地图/仓库/动态 渠道。

新渠道示例 (本次新增): 抓取 CNB 平台公开信息 (开源仓库/组织/用户动态/发布物) 作为
"科技进展 / 开发者生态 / 开源舆论" 类金融相关数据源。

获取方式: 从 params 表读取 url (sitemap/仓库 API), 通用引擎抓取 -> 原始行 -> 字段映射落库。
"""

from __future__ import annotations

from finance.crawler.base import CrawlerBase


class CnbSitemapCrawler(CrawlerBase):
    """CNB 站点信息抓取器: 解析 sitemap / 仓库列表页面。"""

    def parse(self, resp: dict) -> list[dict]:
        text = resp["text"]
        rows = []
        # sitemap XML: <loc> 链接
        if "<urlset" in text or "<sitemapindex" in text:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(text)
                for loc in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                    rows.append({"loc": loc.text or "", "type": "sitemap_url"})
                for loc in root.iter("loc"):  # 无命名空间兜底
                    rows.append({"loc": loc.text or "", "type": "sitemap_url"})
            except Exception:
                pass
            return rows
        # HTML 页面: 提取链接 (href) 与标题 (a 文本)
        from html.parser import HTMLParser

        class LinkParser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    d = dict(attrs)
                    href = d.get("href", "")
                    if href and not href.startswith("#"):
                        self.links.append(href)

        lp = LinkParser()
        lp.feed(text)
        seen = set()
        for href in lp.links:
            if href not in seen:
                seen.add(href)
                rows.append({"loc": href, "type": "html_link"})
        return rows


def fetch(store, payload: dict) -> dict:
    """CNB sitemap 渠道获取入口。"""
    ch = payload["channel"]
    params = payload["params"]
    url = params.get("url") or ch.get("source")
    if not url:
        return {"ok": False, "error": "未配置 url (channels.source 或 params.url)",
                "raw_rows": [], "demo": False}
    crawler = CnbSitemapCrawler(channel_id=payload["channel_id"], params=params)
    rows = crawler.run()
    return {"ok": True, "raw_rows": rows, "demo": False, "detail": {"url": url}}
