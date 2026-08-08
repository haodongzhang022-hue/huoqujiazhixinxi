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

用法:
  python -m reserve.api [--port 8000]
  LANCE_DIR=/path/to/reserve python -m reserve.api
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from reserve.store import ReserveStore
from reserve.preprocessor import normalize_repo, dedupe
from reserve.classifier import classify_batch, load_rules
from reserve.embedding import embed_batch
from reserve.search import search
from reserve.trigger import trigger, rematch_pending_needs


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
            name = path.rsplit("/", 1)[-1]
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
        return self._send(404, {"error": f"no route: {path}"})

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
        return self._send(404, {"error": f"no route: {path}"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/v1/reserve/repos/"):
            name = path.rsplit("/", 1)[-1]
            ok = self.store.delete_repo(name)
            return self._send(200, {"deleted": ok, "full_name": name})
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
