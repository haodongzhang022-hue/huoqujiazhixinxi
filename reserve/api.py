"""储备库 REST API 服务 (api.py) —— 让储备库可被生态内服务/Agent 调用。

对接用户本地 R1/R6 的 API 设计:
  POST /api/v1/reserve/repos        入库 (单条/批量)
  GET  /api/v1/reserve/repos        列表 (可过滤)
  GET  /api/v1/reserve/repos/{name} 详情
  DELETE /api/v1/reserve/repos/{name} 删除
  GET  /api/v1/reserve/search?q=... 检索 (混合)
  POST /api/v1/reserve/match        按能力需求匹配
  POST /api/v1/reserve/trigger      条件触发 (AUTO/SUGGEST/LOG)
  GET  /api/v1/needs                查看 pending_needs
  POST /api/v1/needs/rematch        重匹配 pending_needs

质量/自愈/展示 (v3):
  GET  /api/v1/quality              内容质量评估 (快照+储备库+趋势)
  GET  /api/v1/quality/snapshot     快照质量
  GET  /api/v1/quality/store        储备库质量
  GET  /api/v1/quality/trend        质量趋势
  GET  /api/v1/health               管道健康检查
  POST /api/v1/heal                 触发自愈合
  GET  /api/v1/heal/log             愈合历史
  GET  /api/v1/dashboard/overview   总览
  GET  /api/v1/dashboard/repos      仓库列表 (分页/过滤/排序)
  GET  /api/v1/dashboard/clusters   能力簇
  GET  /api/v1/dashboard/snapshots  每日快照
  GET  /api/v1/dashboard/review     审核队列
  GET  /api/v1/dashboard/needs      待满足需求

Web 页面 (静态托管, 可直接浏览器访问):
  GET  /                             管理页面 (总览)
  GET  /web/*                        静态资源 (index.html / app.js / style.css)

用法:
  python -m reserve.api [--port 8000]
  LANCE_DIR=/path/to/reserve python -m reserve.api
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from reserve.store import ReserveStore
from reserve.preprocessor import normalize_repo, dedupe
from reserve.classifier import classify_batch, load_rules
from reserve.embedding import embed_batch
from reserve.search import search
from reserve.trigger import trigger, rematch_pending_needs
from reserve.llm import get_provider, describe_config, load_config
from reserve.review import review_action_candidates, queue_list, queue_update

# 静态页面目录 (web/)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ReserveAPI(BaseHTTPRequestHandler):
    store = None
    rules = None

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[api] {fmt % args}\n")

    def _send(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        qs = self._query()
        if path == "/api/v1/reserve/repos":
            where = None
            filters = []
            if qs.get("decision"):
                filters.append(f"category_decision = '{qs['decision']}'")
            if qs.get("category"):
                filters.append(f"category = '{qs['category']}'")
            if qs.get("tag"):
                filters.append(f"function_tags LIKE '%{qs['tag']}%'")
            if filters:
                where = " AND ".join(filters)
            limit = int(qs.get("limit", 50))
            rows = self.store.query(where=where, limit=limit)
            return self._send(200, {"count": len(rows), "items": rows})
        if path.startswith("/api/v1/reserve/repos/"):
            from urllib.parse import unquote
            name = qs.get("name") or unquote(path.rsplit("/", 1)[-1])
            repo = self.store.get_repo(name)
            if repo is None:
                return self._send(404, {"error": "not found"})
            return self._send(200, repo)
        if path == "/api/v1/reserve/search":
            q = qs.get("q", "")
            mode = qs.get("mode", "hybrid")
            top = int(qs.get("top", 10))
            results = search(q, top_k=top, mode=mode, store=self.store,
                             decision=qs.get("decision"))
            return self._send(200, {"count": len(results), "items": results})
        if path == "/api/v1/needs":
            return self._send(200, {"needs": self.store.needs_get()})
        if path == "/api/v1/health":
            return self._send(200, {"status": "ok", "reserve_count": self.store.count(),
                                    "tables": self.store.list_tables()})
        if path == "/api/v1/llm/status":
            p = get_provider()
            cfg = load_config()
            return self._send(200, {
                "configured": p is not None,
                "provider": str(p) if p else None,
                "description": describe_config(),
                "config": {k: v for k, v in cfg.items() if k != "api_key"},
                "enrich_enabled": cfg.get("enrich_enabled", True),
                "review_enabled": cfg.get("review_enabled", True),
            })
        if path == "/api/v1/review/queue":
            q = queue_list()
            status = qs.get("status")
            if status:
                q = [e for e in q if e.get("status") == status]
            return self._send(200, {"count": len(q), "items": q})
        if path == "/api/v1/reserve/cluster":
            from reserve.cluster import cluster_by_tags, kmeans, load_repos as cluster_load_repos
            mode = qs.get("mode", "by-tags")
            limit = int(qs.get("limit", 5000))
            repos = cluster_load_repos(limit=limit)
            if mode == "kmeans":
                result = kmeans(repos, k=int(qs.get("k", 6)))
            else:
                result = cluster_by_tags(repos)
            return self._send(200, result)

        # ---------- v3: 质量评估 ----------
        if path == "/api/v1/quality":
            from reserve.quality import build_report
            days = int(qs.get("days", 7))
            return self._send(200, _json_clean(build_report(days=days, store=self.store)))
        if path == "/api/v1/quality/snapshot":
            from reserve.quality import assess_snapshot
            snap = qs.get("path")
            if snap:
                return self._send(200, _json_clean(assess_snapshot(snap)))
            today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
            p = WEB_DIR.parent / "pipeline" / "data" / "snapshots" / f"{today}.json"
            if not p.exists():
                recent = sorted((WEB_DIR.parent / "pipeline" / "data" / "snapshots").glob("*.json"), reverse=True)
                p = recent[0] if recent else p
            return self._send(200, _json_clean(assess_snapshot(p)))
        if path == "/api/v1/quality/store":
            from reserve.quality import assess_store
            return self._send(200, _json_clean(assess_store(self.store)))
        if path == "/api/v1/quality/trend":
            from reserve.quality import assess_trend
            days = int(qs.get("days", 7))
            return self._send(200, _json_clean(assess_trend(days=days)))

        # ---------- v3: 自愈合 ----------
        if path == "/api/v1/health":
            from reserve.self_heal import health_check
            return self._send(200, _json_clean(health_check(self.store)))
        if path == "/api/v1/heal/log":
            from reserve.self_heal import IncidentLog
            limit = int(qs.get("limit", 50))
            return self._send(200, {"incidents": IncidentLog().list(limit=limit)})

        # ---------- v3: 展示视图 ----------
        if path == "/api/v1/dashboard/overview":
            from reserve.dashboard import overview
            days = int(qs.get("days", 7))
            return self._send(200, _json_clean(overview(store=self.store, days=days)))
        if path == "/api/v1/dashboard/repos":
            from reserve.dashboard import repos_view
            return self._send(200, _json_clean(repos_view(
                store=self.store,
                decision=qs.get("decision"), category=qs.get("category"), tag=qs.get("tag"),
                q=qs.get("q"), limit=int(qs.get("limit", 50)), offset=int(qs.get("offset", 0)),
                sort=qs.get("sort", "stars"))))
        if path == "/api/v1/dashboard/clusters":
            from reserve.dashboard import clusters_view
            return self._send(200, _json_clean(clusters_view(
                store=self.store, mode=qs.get("mode", "by-tags"),
                k=int(qs.get("k", 6)))))
        if path == "/api/v1/dashboard/snapshots":
            from reserve.dashboard import snapshots_view
            days = int(qs.get("days", 14))
            return self._send(200, _json_clean(snapshots_view(days=days, store=self.store)))
        if path == "/api/v1/dashboard/review":
            from reserve.dashboard import review_view
            return self._send(200, _json_clean(review_view()))
        if path == "/api/v1/dashboard/needs":
            from reserve.dashboard import needs_view
            return self._send(200, _json_clean(needs_view(store=self.store)))

        # ---------- v4: 多源数据管理器 (ISSUE #5) ----------
        if path == "/api/v1/sources":
            from reserve.sources import list_sources
            return self._send(200, _json_clean(list_sources()))
        if path == "/api/v1/sources/adapters":
            from pipeline.adapters import registry
            return self._send(200, {"items": registry.list_adapters()})
        if path == "/api/v1/digest":
            from reserve.sources import digest
            refresh = qs.get("refresh", "").lower() in ("1", "true", "yes")
            only = qs.get("only", "") or None
            only_list = [x for x in only.split(",") if x] if only else None
            return self._send(200, _json_clean(digest(refresh=refresh, only=only_list)))
        if path.startswith("/api/v1/sources/") and path.endswith("/items"):
            from reserve.sources import CACHE_DIR
            source = path.rsplit("/", 2)[-2]
            cache = CACHE_DIR / f"{source}.json"
            if not cache.exists():
                return self._send(404, {"error": f"source {source} 无缓存, 先拉取"})
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            except Exception as e:
                return self._send(500, {"error": str(e)})
            return self._send(200, payload)
        # ---------- v4.1: 多源条目时间线 (ISSUE #5: LanceDB 按时间/功能排布) ----------
        if path in ("/api/v1/items", "/api/v1/items/timeline"):
            from reserve.feed import get_items_timeline
            return self._send(200, _json_clean(get_items_timeline(
                date=qs.get("date") or None,
                category=qs.get("category") or None,
                source=qs.get("source") or None,
                item_type=qs.get("item_type") or None,
                tag=qs.get("tag") or None,
                limit=int(qs.get("limit", 200)),
                offset=int(qs.get("offset", 0)),
                sort=qs.get("sort", "date_desc"),
            )))
        if path == "/api/v1/items/dates":
            from reserve.store import ReserveStore
            store = ReserveStore()
            return self._send(200, {"dates": store.items_dates(), "total": store.items_count()})

        # ---------- v3: Web 静态页面 ----------
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path.startswith("/web/"):
            return self._serve_static(path[len("/web/"):])

        return self._send(404, {"error": f"no route: {path}"})

    def _serve_static(self, name: str):
        """托管 web/ 静态资源。安全: 只允许 web 目录内文件。"""
        name = name.replace("..", "").lstrip("/")
        p = (WEB_DIR / name).resolve()
        if not str(p).startswith(str(WEB_DIR.resolve())) or not p.exists():
            return self._send(404, {"error": f"not found: {name}"})
        content = p.read_bytes()
        ctype = "text/html; charset=utf-8"
        if p.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif p.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif p.suffix == ".json":
            ctype = "application/json; charset=utf-8"
        elif p.suffix == ".png":
            ctype = "image/png"
        elif p.suffix == ".svg":
            ctype = "image/svg+xml"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/v1/reserve/repos":
            data = self._read_json()
            repos = data.get("repos", data.get("items", [data] if data else []))
            if not repos:
                return self._send(400, {"error": "empty repos"})
            normalized = [normalize_repo(r) for r in repos if r.get("full_name") or r.get("repo_id")]
            dedup = dedupe(normalized, self.store)
            classified = classify_batch(dedup["new"], self.rules)

            # LLM 功能索引增强 (读 README -> function_tags/summary/use_case)
            if data.get("llm_enrich", True):
                from reserve.enrich import enrich_repos
                enrich_repos(classified, fetch_readme=bool(data.get("fetch_readme", False)))

            # LLM 代码审核 (action 候选 -> review + 人工审核队列, 审核结果随行入库)
            if data.get("llm_review", True):
                from reserve.review import review_action_candidates
                try:
                    review_action_candidates(classified, fetch_readme=bool(data.get("fetch_readme", False)))
                except Exception as e:
                    print(f"[api] review step error: {e}")

            embeddings = embed_batch(classified)
            for r, emb in zip(classified, embeddings):
                r["embedding"] = emb
            stats = self.store.upsert_repos(classified)

            return self._send(201, {"upsert": stats, "decisions": _count_decisions(classified)})
        if path == "/api/v1/reserve/match":
            data = self._read_json()
            q = data.get("query") or data.get("q") or data.get("text")
            if not q:
                return self._send(400, {"error": "query required"})
            results = search(q, top_k=int(data.get("top", 10)), store=self.store,
                             decision=data.get("decision"))
            return self._send(200, {"query": q, "count": len(results), "items": results})
        if path == "/api/v1/reserve/trigger":
            data = self._read_json()
            q = data.get("query") or data.get("text")
            if not q:
                return self._send(400, {"error": "query required"})
            res = trigger(q, top_k=int(data.get("top", 5)), store=self.store,
                          decision_filter=data.get("decision"))
            return self._send(200, res)
        if path == "/api/v1/needs/rematch":
            results = rematch_pending_needs(self.store)
            return self._send(200, {"matched": len(results), "results": results})
        if path == "/api/v1/heal":
            """触发自愈合。body: {check_only: bool}（默认 false 自动修复）。"""
            from reserve.self_heal import run_self_heal
            data = self._read_json()
            check_only = bool(data.get("check_only", False))
            result = run_self_heal(check_only=check_only, store=self.store, verbose=False)
            return self._send(200, _json_clean(result))
        if path == "/api/v1/review/run":
            """对 action 候选触发 LLM 代码审核 (可指定快照或直接传 repos)。"""
            data = self._read_json()
            repos = data.get("repos") or data.get("items") or []
            if not repos:
                return self._send(400, {"error": "repos required"})
            review_action_candidates(repos, fetch_readme=bool(data.get("fetch_readme", True)))
            return self._send(200, {"queued": len([r for r in repos if r.get("review_status")])})
        if path == "/api/v1/sources/fetch":
            """拉取全部/指定数据源并写入 LanceDB。body: {only: ["cnb", ...]} 可选。"""
            data = self._read_json()
            only = data.get("only") or data.get("sources") or None
            from reserve.sources import fetch_all_to_store
            out = fetch_all_to_store(only=only)
            ok = sum(1 for r in out["results"] if r.get("ok"))
            return self._send(200, {
                "ok": ok, "total": len(out["results"]),
                "store": out["store"], "results": out["results"],
            })
        if path == "/api/v1/sources/enable":
            """启停数据源。body: {source, enabled}。"""
            data = self._read_json()
            source = data.get("source") or data.get("id")
            enabled = bool(data.get("enabled", True))
            if not source:
                return self._send(400, {"error": "source required"})
            from reserve.sources import set_enabled
            return self._send(200, set_enabled(source, enabled))
        if path == "/api/v1/sources/config":
            """更新某数据源配置。body: {source, config: {...}}。"""
            data = self._read_json()
            source = data.get("source") or data.get("id")
            patch = data.get("config") or data.get("patch") or {}
            if not source:
                return self._send(400, {"error": "source required"})
            from reserve.sources import set_config
            return self._send(200, set_config(source, patch))
        if path == "/api/v1/sources/feeds":
            """新增 RSS 订阅源。body: {name, url, category}。"""
            data = self._read_json()
            name = data.get("name")
            url = data.get("url")
            if not name or not url:
                return self._send(400, {"error": "name and url required"})
            from reserve.sources import add_feed
            return self._send(200, add_feed(name, url, data.get("category", "tech")))
        return self._send(404, {"error": f"no route: {path}"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        qs = self._query()
        name = qs.get("name", "")
        if not name and path.startswith("/api/v1/reserve/repos/"):
            from urllib.parse import unquote
            name = unquote(path.rsplit("/", 1)[-1])
        if name and path.startswith("/api/v1/reserve/repos"):
            ok = self.store.delete_repo(name)
            return self._send(200, {"deleted": ok, "full_name": name})
        return self._send(404, {"error": f"no route: {path}"})

    def do_PUT(self):
        """PUT /api/v1/review/queue?name=owner/repo&status=approved|rejected — 审核队列人工确认。"""
        qs = self._query()
        name = qs.get("name", "")
        if not name and self.path.startswith("/api/v1/review/queue/"):
            # 兼容 path 形式 (URL 编码的 owner%2Frepo 或最后一段)
            from urllib.parse import unquote
            name = unquote(self.path.split("?")[0].rsplit("/", 1)[-1])
        if name and self.path.split("?")[0].startswith("/api/v1/review/queue"):
            status = qs.get("status", "approved")
            if status not in ("approved", "rejected"):
                return self._send(400, {"error": "status must be approved/rejected"})
            entry = queue_update(name, status, note=qs.get("note", ""), reviewer=qs.get("reviewer", "api"))
            return self._send(200, entry if entry else {"error": "not found"})
        return self._send(404, {"error": f"no route: {path}"})

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}


def _count_decisions(repos: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(r.get("category_decision", "none") for r in repos))


def _json_default(o):
    import numpy as np
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _json_clean(obj):
    """递归清理 numpy 类型 -> 原生类型 (JSON 安全序列化)。"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description="储备库 REST API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    ReserveAPI.store = ReserveStore()
    ReserveAPI.rules = load_rules()
    print(f"[api] reserve store: {ReserveAPI.store.uri} | tables: {ReserveAPI.store.list_tables()}")
    print(f"[api] listening on http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), ReserveAPI).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
