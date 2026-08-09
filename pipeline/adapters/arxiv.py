"""pipeline/adapters/arxiv.py — arXiv 论文预印本适配器。

数据来源: arXiv Atom API (export.arxiv.org/api/query, 无需 key)。
默认拉取 cs.AI / cs.CL / cs.LG / cs.SE 分类, 按更新时间排序取最新论文,
解决「新的论文」纳入每日聚合的需求。

配置 (config/sources.json -> sources.arxiv):
  {
    "enabled": true,
    "max_results": 20,
    "categories": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.SE",
    "sort_by": "submittedDate"
  }
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .base import Adapter, AdapterError

ARXIV_API = "http://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivAdapter(Adapter):
    id = "arxiv"
    name = "arXiv 论文预印本"
    category = "papers"
    description = "arXiv cs.AI/cs.CL/cs.LG/cs.SE 最新论文 (Atom API)"

    def fetch(self) -> list[dict]:
        max_results = int(self.config.get("max_results", 20))
        categories = self.config.get(
            "categories",
            "cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.SE",
        )
        sort_by = self.config.get("sort_by", "submittedDate")

        url = (f"{ARXIV_API}?search_query={_quote(categories)}"
               f"&start=0&max_results={max_results}&sortBy={sort_by}&sortOrder=descending")
        raw = self.http_get(url, timeout=25)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: bytes) -> list[dict]:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise AdapterError(f"arxiv: XML 解析失败: {e}") from e
        items = []
        for entry in root.findall("atom:entry", _NS):
            title = _txt(entry, "atom:title")
            summary = _txt(entry, "atom:summary")
            link = ""
            for ln in entry.findall("atom:link", _NS):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href", "")
                    break
            published = _txt(entry, "atom:published")
            authors = [a.findtext("atom:name", default="", namespaces=_NS)
                       for a in entry.findall("atom:author", _NS)]
            id_ = _txt(entry, "atom:id") or link
            items.append({
                "item_id": id_.split("/abs/")[-1] if "/abs/" in id_ else id_,
                "title": re.sub(r"\s+", " ", title).strip(),
                "url": link,
                "summary": re.sub(r"\s+", " ", summary).strip(),
                "published_at": published,
                "category": "papers",
                "tags": ["arxiv"],
                "score": 0,
                "extra": {"authors": [a for a in authors if a], "platform": "arxiv"},
                "raw": {},
            })
        return items


def _txt(entry: ET.Element, path: str) -> str:
    el = entry.find(path, _NS)
    return (el.text or "").strip() if el is not None else ""


def _quote(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(s)


# 注册
from .base import registry  # noqa: E402

registry.register(ArxivAdapter)
