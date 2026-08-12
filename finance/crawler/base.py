"""finance/crawler/base.py —— 通用爬虫引擎基类 (通用模板)。

职责 (与渠道无关的通用能力):
  - HTTP 请求: 超时 / 重试 / 指数退避 / UA 伪装 / 编码探测 / gzip
  - 限流: 每渠道每请求间隔 (从 params 表读取)
  - 解析: JSON / HTML (标准库 html.parser) / RSS (xml.etree) / CSV
  - 分页: 页码 / 游标 / 链接遍历
  - 输出: 原始行 (dict) 列表, 交由 fields.py 映射为标准行

子类只需实现 `parse(response) -> list[dict]` (原始行), 以及可选的
`iter_pages()` / `extract_links()`; 需要 HTTP 之外的获取方式 (如 python 库)
时, 直接用 fetcher 模块调用对应 SDK 即可 (同样走字段映射与落库)。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Iterable


class HtmlTableParser(HTMLParser):
    """极简 HTML 表格解析器 (无第三方依赖, 处理 table/tr/td/th)。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._in_table = 0
        self._in_row = 0
        self._in_cell = 0
        self._cell = []
        self._rows: list[list[str]] = []
        self._cur_row: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table += 1
        elif tag == "tr" and self._in_table:
            self._in_row += 1
            self._cur_row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell += 1
            self._cell = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell -= 1
            text = " ".join("".join(self._cell).split())
            self._cur_row.append(text)
            self._cell = []
        elif tag == "tr" and self._in_row:
            self._in_row -= 1
            if any(c != "" for c in self._cur_row):
                self._rows.append(self._cur_row)
            self._cur_row = []
        elif tag == "table":
            self._in_table -= 1

    def rows(self) -> list[list[str]]:
        return self._rows


class CrawlerBase:
    """通用爬虫引擎基类。

    用法:
        class MyCrawler(CrawlerBase):
            def parse(self, resp: dict) -> list[dict]:
                return [...]

        crawler = MyCrawler(channel_id="xxx")
        raw_rows = crawler.run()
    """

    DEFAULT_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, channel_id: str, params: dict | None = None,
                 timeout: int = 15, max_retries: int = 2,
                 request_interval: float = 0.0):
        self.channel_id = channel_id
        self.params = params or {}
        self.timeout = int(self.params.get("timeout", timeout))
        self.max_retries = int(self.params.get("max_retries", max_retries))
        self.request_interval = float(self.params.get("request_interval", request_interval))
        self.headers = dict(self.DEFAULT_HEADERS)
        if self.params.get("headers"):
            self.headers.update(self.params.get("headers"))
        self.last_request_at = 0.0

    # ---------- 通用 HTTP ----------
    def _throttle(self):
        gap = self.request_interval - (time.time() - self.last_request_at)
        if gap > 0:
            time.sleep(gap)
        self.last_request_at = time.time()

    def http_get(self, url: str, headers: dict | None = None, params: dict | None = None,
                 encoding: str | None = None) -> dict:
        """GET 请求, 返回 {status, text, bytes, url, final_url, headers}。"""
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)
        last_err = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    final_url = resp.geturl()
                    rheaders = dict(resp.headers)
                    if rheaders.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    elif rheaders.get("Content-Encoding") == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            pass
                    text = raw.decode(encoding or "utf-8", errors="replace")
                    return {
                        "status": resp.status, "text": text, "bytes": raw,
                        "url": url, "final_url": final_url, "headers": rheaders,
                    }
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (401, 403, 404):
                    return {"status": e.code, "text": "", "bytes": b"",
                            "url": url, "error": f"HTTP {e.code}"}
            except Exception as e:  # noqa: BLE001
                last_err = e
            if attempt < self.max_retries:
                time.sleep(2 ** attempt)
        return {"status": 0, "text": "", "bytes": b"", "url": url, "error": str(last_err)}

    # ---------- 解析助手 ----------
    def parse_json(self, resp: dict) -> any:
        return json.loads(resp["text"])

    def parse_html_table(self, resp: dict, header_row: bool = True) -> list[dict]:
        """HTML table -> list[dict] (首行为列名时 dict 键=列名)。"""
        parser = HtmlTableParser()
        parser.feed(resp["text"])
        rows = parser.rows()
        if not rows:
            return []
        if not header_row:
            return [{"col%d" % i: v for i, v in enumerate(r)} for r in rows]
        header = [h or f"col{i}" for i, h in enumerate(rows[0])]
        out = []
        for r in rows[1:]:
            out.append(dict(zip(header, r + [""] * (len(header) - len(r)))))
        return out

    def parse_rss(self, resp: dict, fields: tuple = ("title", "link", "pubDate", "description")) -> list[dict]:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp["text"])
        out = []
        for item in root.iter("item"):
            row = {}
            for f in fields:
                el = item.find(f)
                row[f] = el.text if el is not None and el.text else ""
            out.append(row)
        return out

    def parse_csv(self, resp: dict, delimiter: str = ",") -> list[dict]:
        reader = csv.DictReader(io.StringIO(resp["text"]), delimiter=delimiter)
        return [dict(r) for r in reader]

    # ---------- 子类接口 ----------
    def parse(self, resp: dict) -> list[dict]:
        """子类必须实现: 响应 -> 原始行 list[dict]。"""
        raise NotImplementedError

    def iter_urls(self) -> Iterable[str]:
        """子类可覆盖: 返回要抓取的 URL 列表 (分页/多页)。"""
        return []

    # ---------- 入口 ----------
    def run(self) -> list[dict]:
        """抓取所有 URL -> 原始行。"""
        urls = list(self.iter_urls()) or [self.params.get("url")] or [""]
        rows: list[dict] = []
        for url in urls:
            if not url:
                continue
            resp = self.http_get(url)
            if resp.get("status") not in (200, 0) or resp.get("error"):
                rows.append({"_error": str(resp.get("error")), "_url": url})
                continue
            try:
                parsed = self.parse(resp)
                for r in parsed:
                    if isinstance(r, dict):
                        r.setdefault("_url", url)
                        rows.append(r)
            except Exception as e:  # noqa: BLE001
                rows.append({"_error": str(e), "_url": url})
        return rows


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_date_from_text(text: str) -> str | None:
    """从文本提取日期 YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日。"""
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月]", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None
