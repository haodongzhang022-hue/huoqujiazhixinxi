"""finance/api.py —— 金融数据超索引框架 REST API。

路由:
  GET  /api/v1/finance/health                   健康检查
  GET  /api/v1/finance/taxonomy/stats           分类统计
  GET  /api/v1/finance/exchanges?region=CN      交易所查询
  GET  /api/v1/finance/instruments?data_class=&region=&exchange=&trade_type=  品种筛选
  GET  /api/v1/finance/instruments/{id}         品种索引卡
  GET  /api/v1/finance/catalog                  数据源目录
  GET  /api/v1/finance/catalog/{source}/script  数据源获取脚本
  GET  /api/v1/finance/search?data_class=&region=&exchange=&instrument=&time_level=&trade_type=&source=  六维筛选
  GET  /api/v1/finance/disclosure/{level}?instrument=...  渐进式披露 (index/meta/full)
  POST /api/v1/finance/fetch                    触发获取 {instrument, source, time_level, trade_type, refresh}
  GET  /api/v1/finance/schedule                  调度任务列表
  POST /api/v1/finance/schedule                  新增调度任务 {instrument, source, time_level, trade_type, every, at}
  DELETE /api/v1/finance/schedule/{id}           删除调度任务
  POST /api/v1/finance/schedule/run-once         执行到期任务
  GET  /api/v1/finance/cache                     缓存文件索引

用法:
  python -m finance.api --port 8100
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

from finance.taxonomy import load_taxonomy
from finance.catalog import load_catalog
from finance.filter import filter_instruments, match_summary
from finance.disclosure import index_level, meta_level, full_level, list_cache_files
from finance.scheduler import Scheduler


def _json_default(o):
    import numpy as np
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


class FinanceAPI(BaseHTTPRequestHandler):
    tax = None
    cat = None
    sched = None

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[finance-api] {fmt % args}\n")

    def _send(self, code: int, data: dict, ctype: str = "application/json"):
        if ctype == "application/json":
            body = json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8")
        else:
            body = data if isinstance(data, bytes) else str(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype == "application/json" else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> dict:
        qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
        return {k: v[0] for k, v in qs.items()}

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        q = self._query()
        tax = self.tax or load_taxonomy()
        cat = self.cat or load_catalog()

        if path == "/api/v1/finance/health":
            return self._send(200, {"status": "ok", "service": "finance-super-index",
                                    "version": "0.1.0",
                                    "taxonomy": tax.stats(),
                                    "catalog": cat.summary()})
        if path == "/api/v1/finance/taxonomy/stats":
            return self._send(200, tax.stats())
        if path == "/api/v1/finance/exchanges":
            region = q.get("region")
            if region:
                return self._send(200, {"region": region, "exchanges": tax.exchanges_of_region(region)})
            return self._send(200, {"exchanges": list(tax.exchanges.values())})
        if path == "/api/v1/finance/instruments":
            result = tax.instruments_of(data_class=q.get("data_class"), region=q.get("region"),
                                        exchange=q.get("exchange"), trade_type=q.get("trade_type"))
            return self._send(200, {"count": len(result), "items": result})
        if path.startswith("/api/v1/finance/instruments/"):
            iid = unquote(path.rsplit("/", 1)[-1])
            card = tax.describe_instrument(iid)
            if not card:
                return self._send(404, {"error": f"instrument not found: {iid}"})
            return self._send(200, card)
        if path == "/api/v1/finance/catalog":
            sid = q.get("source")
            if sid:
                info = cat.script_of(sid)
                if not info:
                    return self._send(404, {"error": f"source not found: {sid}"})
                return self._send(200, info)
            return self._send(200, {"sources": cat.list_sources(), "summary": cat.summary()})
        if path.startswith("/api/v1/finance/catalog/"):
            sid = unquote(path.rsplit("/", 1)[-1])
            info = cat.script_of(sid)
            if not info:
                return self._send(404, {"error": f"source not found: {sid}"})
            return self._send(200, info)
        if path == "/api/v1/finance/search":
            result = filter_instruments(tax, cat, data_class=q.get("data_class"),
                                        region=q.get("region"), exchange=q.get("exchange"),
                                        trade_type=q.get("trade_type"), instrument=q.get("instrument"),
                                        time_level=q.get("time_level"), source=q.get("source"))
            mode = q.get("mode", "detail")
            if mode == "summary":
                return self._send(200, match_summary(result))
            return self._send(200, {"count": len(result), "items": result})
        if path.startswith("/api/v1/finance/disclosure/"):
            level = path.rsplit("/", 1)[-1]
            instrument = q.get("instrument", "")
            if not instrument:
                return self._send(400, {"error": "instrument required"})
            if level == "index":
                return self._send(200, index_level(instrument))
            if level == "meta":
                return self._send(200, meta_level(instrument))
            if level == "full":
                r = full_level(instrument, source=q.get("source"), time_level=q.get("time_level"),
                               trade_type=q.get("trade_type"), refresh=q.get("refresh") == "1")
                return self._send(200, r)
            return self._send(404, {"error": f"unknown level: {level}"})
        if path == "/api/v1/finance/schedule":
            return self._send(200, {"tasks": (self.sched or Scheduler()).list()})
        if path == "/api/v1/finance/cache":
            return self._send(200, {"files": list_cache_files()})
        return self._send(404, {"error": f"no route: {path}"})

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        tax = self.tax or load_taxonomy()
        if path == "/api/v1/finance/fetch":
            body = self._read_json()
            instrument = body.get("instrument", "")
            if not instrument:
                return self._send(400, {"error": "instrument required"})
            inst = tax.resolve_instrument(instrument)
            if not inst:
                return self._send(404, {"error": f"instrument not found: {instrument}"})
            from finance.registry import fetch_instrument
            result = fetch_instrument(inst, source=body.get("source", "manual"),
                                      time_level=body.get("time_level"),
                                      trade_type=body.get("trade_type"),
                                      refresh=bool(body.get("refresh", False)),
                                      force_demo=bool(body.get("force_demo", False)))
            return self._send(200, result)
        if path == "/api/v1/finance/schedule":
            body = self._read_json()
            sched = self.sched or Scheduler()
            if not body.get("instrument") or not body.get("source"):
                return self._send(400, {"error": "instrument and source required"})
            task = sched.add(body["instrument"], body["source"],
                             time_level=body.get("time_level"), trade_type=body.get("trade_type"),
                             every=body.get("every"), at=body.get("at"))
            return self._send(201, {"task": task})
        if path == "/api/v1/finance/schedule/run-once":
            sched = self.sched or Scheduler()
            results = sched.run_due()
            return self._send(200, {"triggered": len(results), "results": results})
        return self._send(404, {"error": f"no route: {path}"})

    # ---------- DELETE ----------
    def do_DELETE(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.startswith("/api/v1/finance/schedule/"):
            tid = unquote(path.rsplit("/", 1)[-1])
            sched = self.sched or Scheduler()
            ok = sched.remove(tid)
            return self._send(200 if ok else 404, {"deleted": ok, "task_id": tid})
        return self._send(404, {"error": f"no route: {path}"})


def run(port: int = 8100, host: str = "0.0.0.0"):
    FinanceAPI.tax = load_taxonomy()
    FinanceAPI.cat = load_catalog()
    FinanceAPI.sched = Scheduler()
    server = ThreadingHTTPServer((host, port), FinanceAPI)
    print(f"[finance-api] 金融数据超索引框架 REST API 启动: http://127.0.0.1:{port}")
    print(f"  健康检查    GET  /api/v1/finance/health")
    print(f"  六维筛选    GET  /api/v1/finance/search?data_class=futures&region=CN")
    print(f"  品种索引卡  GET  /api/v1/finance/instruments/CN.RB")
    print(f"  数据源目录  GET  /api/v1/finance/catalog")
    print(f"  渐进披露    GET  /api/v1/finance/disclosure/meta?instrument=CN.RB")
    print(f"  触发获取    POST /api/v1/finance/fetch")
    print(f"  调度管理    GET/POST /api/v1/finance/schedule")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[finance-api] 已停止")
        server.server_close()


def main():
    ap = argparse.ArgumentParser(description="金融数据超索引框架 REST API")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    run(port=args.port, host=args.host)


if __name__ == "__main__":
    main()
