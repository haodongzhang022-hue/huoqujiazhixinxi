"""finance/lance/discovery.py —— 挖掘新数据渠道的定时脚本爬虫 (discovery_candidates 表)。

对齐 Issue #6: "建立一个挖掘新渠道数据的定时脚本爬虫"

能力:
  1. 发现 (discover): 从预设挖掘引擎抓取候选渠道
       - cnb 平台: 仓库/组织/动态 (公开 API + 页面)
       - 热门数据源索引: awesome-* 列表、公开 API 目录 (github)
       - 已有渠道的扩展: 同域其它端点/相关站点
  2. 评估 (evaluate): 对候选探测 (可达性/内容类型/字段), 打分 0-100
  3. 转正 (promote): 候选 -> channels + column_defs + params 三表入库 (状态 promoted)
  4. 自动任务: 注册为 interval 任务 (默认每 1d), 由 TaskManager 周期触发

挖掘引擎 (discovery engines): 每个引擎一个函数, 返回候选列表
  - cnb_platform:    CNB 平台仓库/组织 (https://cnb.cool 公开页)
  - awesome_github:  GitHub awesome 金融数据源清单
  - seed_expansion:  从现有渠道的 coverage 反查未覆盖区域/类别
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin

from finance.crawler.base import CrawlerBase
from finance.lance.store import get_store, json_dumps

DEFAULT_ENGINES = ["cnb_platform", "seed_expansion"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DiscoveryCrawler(CrawlerBase):
    """通用挖掘爬虫: 抓取候选页 -> 提取链接/条目。"""

    def parse(self, resp: dict) -> list[dict]:
        text = resp["text"]
        rows = []
        if "<urlset" in text or "<sitemapindex" in text:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(text)
                for loc in root.iter("loc"):
                    rows.append({"url": loc.text or "", "title": "", "type": "url"})
            except Exception:
                pass
            return rows
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.items = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    d = dict(attrs)
                    href = d.get("href", "")
                    title = d.get("title", "")
                    if href and not href.startswith(("#", "javascript:")):
                        self.items.append((href, title))

        p = P()
        p.feed(text)
        for href, title in p.items:
            rows.append({"url": href, "title": title, "type": "link"})
        return rows


class ChannelDiscovery:
    """渠道挖掘器。"""

    def __init__(self, store=None):
        self.store = store or get_store()

    # ---------- 发现 ----------
    def discover(self, engines: list[str] | None = None, dry_run: bool = False) -> list[dict]:
        engines = engines or DEFAULT_ENGINES
        all_candidates = []
        for eng in engines:
            fn = getattr(self, f"_engine_{eng}", None)
            if not fn:
                continue
            try:
                cands = fn()
                for c in cands:
                    c["discovery_source"] = eng
                    c["candidate_id"] = _candidate_id(c)
                    all_candidates.append(c)
            except Exception as e:  # noqa: BLE001
                print(f"[discovery] 引擎 {eng} 失败: {e}")
        # 去重 (url)
        seen = set()
        unique = []
        for c in all_candidates:
            url = c.get("url", "")
            if url in seen:
                continue
            seen.add(url)
            unique.append(c)
        # 入库
        if not dry_run:
            self._save_candidates(unique)
        return unique

    def _engine_cnb_platform(self) -> list[dict]:
        """CNB 平台: 抓取公开仓库/组织列表 (cnb.cool 首页 + sitemap)。"""
        crawler = DiscoveryCrawler(channel_id="discovery", params={"request_interval": 0.4})
        cands = []
        for url in ("https://cnb.cool/explore", "https://cnb.cool/"):
            resp = crawler.http_get(url)
            if resp.get("status") != 200 or resp.get("error"):
                continue
            rows = crawler.parse(resp)
            for r in rows:
                u = r.get("url", "")
                if not u or not u.startswith("/"):
                    continue
                full = urljoin("https://cnb.cool", u)
                if full in ("https://cnb.cool/", "https://cnb.cool/explore"):
                    continue
                cands.append({
                    "name": r.get("title") or full,
                    "url": full,
                    "kind": "website",
                    "data_classes": ["opensource", "sentiment", "macro"],
                    "regions": ["GLOBAL", "CN"],
                    "notes": "CNB 平台公开仓库/组织, 可获取开发者生态/科技进展数据",
                })
        return cands

    def _engine_seed_expansion(self) -> list[dict]:
        """从现有渠道的 coverage 反查未覆盖区域, 给出扩展建议候选。"""
        from finance.catalog import load_catalog
        cat = load_catalog()
        covered = set()
        for s in cat.sources:
            for r in s.get("coverage", {}).get("regions", []):
                covered.add(r)
        all_regions = {"CN", "HK", "US", "JP", "KR", "TW", "SG", "EU", "UK", "DE", "FR", "AU"}
        missing = sorted(all_regions - covered)
        cands = []
        region_apis = {
            "JP": "https://www.jpx.co.jp/english/markets/",
            "KR": "https://open.krx.co.kr/",
            "TW": "https://www.twse.com.tw/en/",
            "DE": "https://www.xetra.com/",
            "AU": "https://www.asx.com.au/",
        }
        for r in missing:
            cands.append({
                "name": f"{r} 地区金融数据源",
                "url": region_apis.get(r, ""),
                "kind": "http_api",
                "data_classes": ["stock", "futures"],
                "regions": [r],
                "notes": f"现有渠道未覆盖 {r} 地区, 建议补充当地交易所/宏观数据源",
            })
        return cands

    # ---------- 评估 ----------
    def evaluate(self, candidate_id: str | None = None, limit: int = 20) -> list[dict]:
        """对候选做可达性/内容探测并打分。"""
        cands = self.list_candidates(status="new", limit=limit) if not candidate_id \
            else [self.get_candidate(candidate_id)]
        results = []
        for c in cands:
            if not c:
                continue
            score, probe = self._probe(c)
            c["score"] = score
            c["probe_result"] = json_dumps(probe)
            c["status"] = "evaluated" if score >= 30 else "rejected"
            c["updated_at"] = _now()
            self.store.upsert("discovery_candidates", [self._ser_candidate(c)], "candidate_id")
            results.append({"candidate_id": c["candidate_id"], "name": c.get("name"),
                            "url": c.get("url"), "score": score, "status": c["status"]})
        return results

    @staticmethod
    def _ser_candidate(c: dict) -> dict:
        """写回前序列化 JSON 列 (LanceDB string 列不能存 list/dict)。"""
        out = dict(c)
        for f in ("data_classes", "regions", "probe_result", "ext"):
            if f in out and not isinstance(out[f], str):
                out[f] = json_dumps(out[f])
        return out

    def _probe(self, c: dict) -> tuple[int, dict]:
        url = c.get("url", "")
        if not url:
            return 0, {"error": "无 url"}
        crawler = DiscoveryCrawler(channel_id="discovery", params={"request_interval": 0.3})
        resp = crawler.http_get(url)
        status = resp.get("status")
        if status != 200 or resp.get("error"):
            return 5, {"status": status, "error": str(resp.get("error"))}
        text = resp["text"]
        probe = {"status": status, "size": len(text), "final_url": resp.get("final_url")}
        score = 30
        if "<html" in text.lower() or "<urlset" in text or "<rss" in text.lower() or "<feed" in text.lower():
            score += 20
            probe["has_html"] = True
        if re.search(r"(api|json|xml|csv|rss|feed|data)", url.lower()):
            score += 15
            probe["data_like_url"] = True
        if re.search(r"(price|quote|stock|future|forex|macro|index|finance|rate|market)", text.lower()[:20000]):
            score += 15
            probe["finance_keywords"] = True
        if "<table" in text.lower() or "application/json" in resp.get("headers", {}).get("Content-Type", ""):
            score += 10
            probe["has_table_or_json"] = True
        return min(score, 95), probe

    # ---------- 转正 ----------
    def promote(self, candidate_id: str, channel_id: str | None = None,
                kind: str | None = None, data_classes: list | None = None,
                regions: list | None = None, source: str | None = None,
                module: str | None = None) -> dict:
        """候选 -> 正式渠道 (channels + column_defs + params)。"""
        c = self.get_candidate(candidate_id)
        if not c:
            return {"ok": False, "error": f"候选不存在: {candidate_id}"}
        cid = channel_id or _slugify(c.get("name") or candidate_id)
        ch = {
            "channel_id": cid,
            "name": c.get("name", cid),
            "name_en": cid,
            "kind": kind or c.get("kind", "website"),
            "data_classes": data_classes or c.get("data_classes", []),
            "regions": regions or c.get("regions", []),
            "exchanges": [],
            "status": "active",
            "source": source or c.get("url", ""),
            "method": "http_get",
            "script": "",
            "module": module or "",
            "command": "",
            "auth": {},
            "rate_limit": "",
            "storage": {"kind": "lancedb", "table": "data_records"},
            "schedule": {"default_frequency": "1d"},
            "disclosure": {"index": True, "meta": True, "full": True},
            "requires": {},
            "fetchers": [],
            "enabled": False,  # 转正后默认不自动启用, 待人工确认列定义
            "discovered_from": candidate_id,
        }
        from finance.lance.registry import ChannelRegistry
        reg = ChannelRegistry(self.store)
        reg.register_channel(ch)
        # 通用列定义 (可后续按渠道调整)
        reg.add_column_def(cid, "title", "title", "string", "标题")
        reg.add_column_def(cid, "url", "link", "string", "链接")
        reg.add_column_def(cid, "link", "link", "string", "链接")
        reg.add_column_def(cid, "date", "ts", "datetime", "日期")
        reg.add_column_def(cid, "value", "value", "float", "数值")
        # 更新候选状态
        c["status"] = "promoted"
        c["promoted_channel_id"] = cid
        c["updated_at"] = _now()
        self.store.upsert("discovery_candidates", [self._ser_candidate(c)], "candidate_id")
        return {"ok": True, "channel_id": cid, "candidate_id": candidate_id}

    # ---------- 存储 ----------
    def _save_candidates(self, cands: list[dict]):
        now = _now()
        rows = []
        for c in cands:
            rows.append({
                "candidate_id": c.get("candidate_id", str(uuid.uuid4())),
                "name": c.get("name", ""),
                "url": c.get("url", ""),
                "discovery_source": c.get("discovery_source", ""),
                "kind": c.get("kind", "website"),
                "data_classes": json_dumps(c.get("data_classes", [])),
                "regions": json_dumps(c.get("regions", [])),
                "notes": c.get("notes", ""),
                "status": "new",
                "score": 0,
                "probe_result": json_dumps({}),
                "promoted_channel_id": "",
                "created_at": now,
                "updated_at": now,
            })
        self.store.upsert("discovery_candidates", rows, "candidate_id")

    def list_candidates(self, status: str | None = None, limit: int = 50) -> list[dict]:
        where = f"status = '{status}'" if status else None
        return self.store.query("discovery_candidates", where=where, limit=limit,
                                order_by="updated_at")

    def get_candidate(self, candidate_id: str) -> dict | None:
        return self.store.get("discovery_candidates", "candidate_id", candidate_id)

    # ---------- 一键流程 ----------
    def run_pipeline(self, engines: list[str] | None = None, auto_promote: bool = False) -> dict:
        """发现 -> 评估 -> (可选) 自动转正。"""
        t0 = time.time()
        found = self.discover(engines)
        evaluated = self.evaluate()
        promoted = []
        if auto_promote:
            for e in evaluated:
                if e.get("score", 0) >= 70:
                    r = self.promote(e["candidate_id"])
                    if r.get("ok"):
                        promoted.append(r["channel_id"])
        # 注册定时挖掘任务 (每 1d)
        from finance.lance.tasks import TaskManager
        tm = TaskManager(self.store)
        existing = [t for t in tm.list() if t.get("channel_id") == "discovery"]
        if not existing:
            tm.add(channel_id="discovery", name="渠道挖掘定时任务", every="1d",
                   params={"engines": engines or DEFAULT_ENGINES})
        from finance.lance.logs import RunLogger
        RunLogger(self.store).log(
            "discovery", status="ok",
            message=f"挖掘完成: 发现 {len(found)} / 评估 {len(evaluated)} / 转正 {len(promoted)}",
            rows_count=len(found), duration_ms=int((time.time() - t0) * 1000),
            detail={"found": found[:10], "evaluated": evaluated, "promoted": promoted})
        return {"found": len(found), "evaluated": len(evaluated), "promoted": promoted,
                "candidates": evaluated}


def _candidate_id(c: dict) -> str:
    url = c.get("url", "")
    return "cand-" + str(abs(hash(url)) % 10_000_000) if url else "cand-" + str(uuid.uuid4())[:8]


def _slugify(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", name).strip("-").lower()
    return s[:48] or "channel"
