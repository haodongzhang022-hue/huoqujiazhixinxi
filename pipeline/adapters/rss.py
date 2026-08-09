"""pipeline/adapters/rss.py — 通用 RSS/Atom 适配器 (科技进展 / 站点更新)。

用于聚合任意支持 RSS/Atom 的站点 (公司技术博客、开源社区、新闻站) —
满足「聚合其他有开源项目的站 + 科技进展」的通用需求。新增站点只需在
config/sources.json 的 sources.rss.feeds 里加一行 URL。

配置 (config/sources.json -> sources.rss):
  {
    "enabled": true,
    "max_per_feed": 10,
    "feeds": [
      {"url": "https://.../feed.xml", "name": "站点名", "category": "tech"},
      ...
    ]
  }
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .base import Adapter, AdapterError

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss": "",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


class RSSAdapter(Adapter):
    id = "rss"
    name = "RSS/Atom 订阅源"
    category = "tech"
    description = "通用 RSS/Atom 聚合 (科技进展 / 站点更新 / 博客)"

    def fetch(self) -> list[dict]:
        feeds = self.config.get("feeds") or []
        if not feeds:
            raise AdapterError("rss: 未配置 feeds (config/sources.json -> sources.rss.feeds)")
        max_per_feed = int(self.config.get("max_per_feed", 10))
        items: list[dict] = []
        for feed in feeds:
            url = feed.get("url")
            if not url:
                continue
            name = feed.get("name") or url
            category = feed.get("category") or "tech"
            try:
                raw = self.http_get(url, timeout=20)
                parsed = self._parse(raw, name, category)
                items.extend(parsed[:max_per_feed])
            except AdapterError as e:
                print(f"[rss] {name}: 跳过 ({e})", flush=True)
        return items

    @staticmethod
    def _parse(raw: bytes, name: str, category: str) -> list[dict]:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise AdapterError(f"rss: XML 解析失败: {e}") from e

        items = []
        if root.tag.endswith("}feed") or root.tag == "feed":  # Atom
            for entry in root.findall("atom:entry", _NS):
                title = _txt(entry, "atom:title")
                link = ""
                for ln in entry.findall("atom:link", _NS):
                    if ln.get("rel", "alternate") == "alternate" or ln.get("href"):
                        link = ln.get("href", "")
                        break
                published = _txt(entry, "atom:published") or _txt(entry, "atom:updated")
                items.append({
                    "item_id": f"{name}-{title}",
                    "title": title,
                    "url": link or _txt(entry, "atom:id"),
                    "summary": _txt(entry, "atom:summary"),
                    "published_at": published,
                    "category": category,
                    "tags": [name],
                    "score": 0,
                    "extra": {"feed": name},
                    "raw": {},
                })
        else:  # RSS 2.0
            for entry in root.findall("./channel/item"):
                title = _txt(entry, "title")
                link = _txt(entry, "link")
                published = _txt(entry, "pubDate") or _txt(entry, "dc:date")
                items.append({
                    "item_id": f"{name}-{title}",
                    "title": title,
                    "url": link,
                    "summary": _txt(entry, "description"),
                    "published_at": published,
                    "category": category,
                    "tags": [name],
                    "score": 0,
                    "extra": {"feed": name},
                    "raw": {},
                })
        return items


def _txt(entry: ET.Element, path: str) -> str:
    el = entry.find(path, _NS)
    if el is None and path.startswith("dc:"):
        el = entry.find(f"{{{_NS['dc']}}}{path.split(':', 1)[1]}")
    if el is None and path.startswith("content:"):
        el = entry.find(f"{{{_NS['content']}}}{path.split(':', 1)[1]}")
    if el is None:
        return ""
    text = "".join(el.itertext())
    return re.sub(r"\s+", " ", text).strip()


# 注册
from .base import registry  # noqa: E402

registry.register(RSSAdapter)
