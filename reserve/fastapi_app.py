"""reserve/fastapi_app.py — FastAPI 聚合管理页面 + 对外信息流 API。

ISSUE #4 落地：在既有 http.server REST API (reserve/api.py) 之上，
新增 FastAPI 服务，提供：

  A. 聚合管理页面 (人类优先浏览):
     GET  /                   管理台页面 (单页应用, 总览/今日汇总/仓库/能力簇/质量/快照/需求/审核/数据源)
     GET  /web/*              静态资源

  B. 对外信息流 (人类优先 / AI 优先, 一次获取多人使用 + 允许 AI 直接消费):
     GET  /api/v1/feed?mode=human|ai&date=&category=&decision=&limit=&offset=
     GET  /api/v1/feed/{date}?mode=...
     GET  /api/v1/sources               数据源注册表 (含 CNB/论文/热点/新闻 预留位)
     GET  /api/v1/health                服务健康 (含数据源状态)
     POST /api/v1/sync/{source}         预留: 单源手动同步 (扩展数据源时实现)

  C. 兼容既有储备库管理 API (REST, 与 reserve/api.py 对齐):
     /api/v1/dashboard/*  /api/v1/quality/*  /api/v1/reserve/*
     /api/v1/search  /api/v1/match  /api/v1/trigger  /api/v1/needs/*
     /api/v1/review/*  /api/v1/health|heal  /api/v1/llm/status

启动:
  python -m reserve.fastapi_app --port 8000
  # 或
  uvicorn reserve.fastapi_app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reserve.schemas import AiFeed, DailyDigest, HumanFeed, PublicHealth, SourceSyncResult
from reserve.relations.schemas import (RelationComparison, RelationEdge, RelationMatrix,
                                       ModelCompareResult, RelationNetwork)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

app = FastAPI(
    title="开源项目信息聚合管理台 (Reserve FastAPI)",
    description=(
        "每天自动获取开源项目信息，一次获取、多人共享；"
        "提供 人类优先(human) / AI 优先(ai) 双信息流，AI 可直接消费搭建自动化流程。"
        "预留 CNB 新项目 / 论文 / 热点 / 科技新闻 数据源扩展位。"
        "二次整理层: 金融各市场/品种间两两关联量化 + 预测 vs 实际对比 (ISSUE #7)。"
    ),
    version="1.0.0",
)

# ---------------- 数据模型 ----------------

class MatchBody(BaseModel):
    query: Optional[str] = None
    q: Optional[str] = None
    text: Optional[str] = None
    top: int = 10
    decision: Optional[str] = None


class TriggerBody(BaseModel):
    query: Optional[str] = None
    text: Optional[str] = None
    top: int = 5
    decision: Optional[str] = None


class HealBody(BaseModel):
    check_only: bool = False


class SyncBody(BaseModel):
    date: Optional[str] = None


# ---------------- 工具 ----------------

def _store():
    from reserve.store import ReserveStore
    return ReserveStore()


def _clean(obj):
    import numpy as np
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    idx = WEB_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse("<h1>web/index.html not found</h1>", status_code=404)
    return HTMLResponse(idx.read_text(encoding="utf-8"))


@app.get("/web/{path:path}", include_in_schema=False)
def web_static(path: str):
    p = (WEB_DIR / path).resolve()
    if not str(p).startswith(str(WEB_DIR.resolve())) or not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


# ---------------- 对外信息流 (核心新增) ----------------

@app.get("/api/v1/sources", response_model=list, tags=["对外信息流"])
def api_sources():
    """数据源注册表: 已接入 + 预留扩展位 (CNB 新项目/论文/热点/新闻)。"""
    from reserve.feed import list_sources
    return _clean(list_sources())


@app.get("/api/v1/feed", response_model=None, tags=["对外信息流"])
def api_feed(
    mode: str = Query("human", pattern="^(human|ai)$", description="human=人类优先 / ai=AI优先"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD, 默认今日"),
    category: Optional[str] = Query(None, description="生态分类 (mcp-servers/ai-agents/...)"),
    decision: Optional[str] = Query(None, description="action/reserve/partial/ignore"),
    tag: Optional[str] = Query(None, description="功能标签过滤 (仅 ai 模式)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """人类优先 / AI 优先 信息流 (对外公开)。

    - mode=human: 按生态分类分组, 中文摘要 + 标签 + 场景 + 审核建议 (适合人浏览)
    - mode=ai   : 扁平条目 + content 正文, 机器可直接消费 (适合自动化/Agent)
    """
    from reserve.feed import get_feed, _filter_items
    data = get_feed(mode=mode, date=date, limit=limit, offset=offset,
                    category=category, decision=decision)
    if tag and mode == "ai":
        items = [it for it in data.get("items", []) if tag in (it.get("function_tags") or [])]
        data["items"] = items[offset:offset + limit]
        data["meta"]["total"] = len(items)
        data["meta"]["tag"] = tag
    return _clean(data)


@app.get("/api/v1/feed/{date}", response_model=None, tags=["对外信息流"])
def api_feed_by_date(
    date: str,
    mode: str = Query("human", pattern="^(human|ai)$"),
    category: Optional[str] = None,
    decision: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """指定日期的历史信息流。"""
    from reserve.feed import get_feed
    return _clean(get_feed(mode=mode, date=date, limit=limit, offset=offset,
                           category=category, decision=decision))


@app.get("/api/v1/digest/{date}", response_model=None, tags=["对外信息流"])
def api_digest(date: Optional[str] = None):
    """每日聚合摘要 (各数据源 + 统计 + 分组信息流), 供管理页「今日汇总」与外部订阅。"""
    from reserve.feed import get_feed, list_sources
    date = date or _today()
    data = get_feed(mode="human", date=date, limit=200)
    from collections import Counter
    items = []
    for sec in data.get("sections", []):
        items.extend(sec.get("items", []))
    decisions = Counter(it.get("category_decision") or "none" for it in items)
    cats = Counter(it.get("category") or "unknown" for it in items)
    new_count = sum(1 for it in items if it.get("is_new"))
    action_count = sum(1 for it in items if it.get("category_decision") == "action")
    total_stars = sum(it.get("stars") or 0 for it in items)
    return _clean({
        "date": date,
        "generated_at": data["meta"]["generated_at"],
        "stats": {
            "total_items": len(items),
            "new_this_week": new_count,
            "action_candidates": action_count,
            "total_stars": total_stars,
            "decisions": dict(decisions),
            "categories": dict(cats),
        },
        "sources": list_sources(),
        "sections": data.get("sections", []),
        "headline": data.get("headline", {}),
    })


@app.post("/api/v1/sync/{source}", response_model=SourceSyncResult, tags=["对外信息流"])
def api_sync_source(source: str, body: SyncBody | None = None):
    """预留: 单数据源手动同步。

    当前仅 github-repos 有真实实现 (重跑 pipeline.fetch 落当日快照);
    cnb-projects / papers / tech-trends / news 为预留位, 待后续 ISSUE 接入。
    """
    from reserve.feed import list_sources
    known = {s["id"] for s in list_sources()}
    if source not in known:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")

    if source == "github-repos":
        try:
            import subprocess
            env = dict(os.environ)
            env.pop("GITHUB_TOKEN", None)
            proc = subprocess.run(
                [sys.executable, "-m", "pipeline.fetch"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=1800, env=env,
            )
            return SourceSyncResult(source=source, status="active", items=0,
                                    message=f"fetch 输出: {proc.stdout[-500:]}")
        except Exception as e:
            return SourceSyncResult(source=source, status="error", items=0, message=str(e))
    # 预留源: 返回待接入提示 (不报错, 让前端/外部知道是预留位)
    return SourceSyncResult(
        source=source, status="reserved", items=0,
        message=f"数据源 {source} 为预留扩展位, 将在后续 ISSUE 中接入",
    )


# ---------------- 二次整理层: 金融各市场两两关联 (ISSUE #7) ----------------


def _relation_store():
    from reserve.relations.store import RelationStore
    return RelationStore()


def _dim_key_of(d: dict) -> str:
    return ".".join([str(d.get(k, "*")) for k in ("market", "country", "exchange", "symbol", "asset", "timeframe")])


@app.get("/api/v1/relations/matrix", response_model=None, tags=["二次整理层"])
def api_relations_matrix():
    """关联矩阵骨架: 目标集 -> 全两两有序边 (排除自环, 方向敏感)。"""
    store = _relation_store()
    matrix = store.load_matrix()
    if matrix is None:
        return {"schema_version": "1.0", "dimensions": [], "dimension_keys": [],
                "pair_count": 0, "pairs": [], "note": "尚未构建矩阵, 先运行 python -m reserve.relations.demo"}
    return _clean(matrix)


@app.get("/api/v1/relations/edges", response_model=None, tags=["二次整理层"])
def api_relations_edges(
    min_strength: float = Query(0.0, ge=0.0, le=1.0),
    model: Optional[str] = Query(None, description="模型类型过滤"),
    verdict: Optional[str] = Query(None, description="预测能力评价过滤: strong/good/weak/insufficient"),
    rel: Optional[str] = Query(None, description="关系类型过滤: intra_layer(层内) | inter_layer(层间)"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    sort: str = Query("strength", description="strength|stability|lag|sample_size"),
):
    """两两关联边列表 (A→B, 每条独立)。支持按功能域分层漏斗筛选。"""
    from reserve.relations.dims import relationship_kind
    store = _relation_store()
    edges = store.list_edges()
    # 附带预测对比摘要 (verdict / 测试段指标), 便于表格直接展示预测能力
    comps = {c.get("edge"): c for c in store.list_comparisons()}
    for e in edges:
        c = comps.get(e.get("edge"))
        if c:
            e["comparison"] = {"verdict": c.get("verdict"),
                               "metrics": c.get("metrics"),
                               "iterations": c.get("iterations")}
        # 标注层内/层间 (分层漏斗筛选)
        try:
            e["relation_kind"] = relationship_kind(e.get("from") or {}, e.get("to") or {})["kind"]
            e["intra_layer"] = e["relation_kind"] == "intra_layer"
            e["inter_layer"] = e["relation_kind"] == "inter_layer"
        except Exception:
            e["relation_kind"] = ""
    if model:
        edges = [e for e in edges if e.get("model") == model]
    if verdict:
        comps = {c.get("edge"): c.get("verdict") for c in store.list_comparisons()}
        edges = [e for e in edges if comps.get(e.get("edge")) == verdict]
    if rel:
        edges = [e for e in edges if e.get("relation_kind") == rel]
    edges = [e for e in edges if (e.get("strength") or 0.0) >= min_strength]
    rev = sort == "strength" or sort == "stability" or sort == "sample_size"
    key_fn = {"strength": lambda e: e.get("strength") or 0.0,
              "stability": lambda e: e.get("stability") or 0.0,
              "lag": lambda e: e.get("lag") or 0,
              "sample_size": lambda e: e.get("sample_size") or 0}.get(sort, lambda e: e.get("strength") or 0.0)
    edges.sort(key=key_fn, reverse=rev)
    total = len(edges)
    page = edges[offset:offset + limit]
    return _clean({"count": total, "limit": limit, "offset": offset, "items": page})


@app.get("/api/v1/relations/edge/{edge:path}", response_model=None, tags=["二次整理层"])
def api_relations_edge(edge: str):
    """单条边详情 (含关联评估 + 预测 vs 实际对比)。"""
    store = _relation_store()
    from urllib.parse import unquote
    edge = unquote(edge)
    result = store.load_edge(edge)
    if result is None:
        raise HTTPException(status_code=404, detail=f"edge not found: {edge}")
    comparison = store.load_comparison(edge)
    if comparison is not None:
        result["comparison"] = comparison
    # 附带序列快照 key (供前端多模型对比)
    result["series_available"] = bool(store.load_series(_dim_key_of(result.get("from") or {})))
    return _clean(result)


@app.get("/api/v1/relations/comparisons", response_model=None, tags=["二次整理层"])
def api_relations_comparisons(
    verdict: Optional[str] = Query(None, description="预测能力评价过滤"),
    limit: int = Query(200, ge=1, le=2000),
):
    """预测 vs 实际 对比列表 (验证预测能力到底够不够)。"""
    store = _relation_store()
    comps = store.list_comparisons()
    if verdict:
        comps = [c for c in comps if c.get("verdict") == verdict]
    comps.sort(key=lambda c: -(c.get("metrics") or {}).get("r2") or 0.0)
    return _clean({"count": len(comps), "items": comps[:limit]})


@app.post("/api/v1/relations/evaluate", response_model=None, tags=["二次整理层"])
def api_relations_evaluate(body: dict):
    """实时评估两条序列的关联 (A→B)。

    body: {"series_a": {日期: 值}, "series_b": {日期: 值},
           "model": "linear", "max_lag": 10, "lag": null,
           "label_a": "...", "label_b": "..."}   # label 可选, 用于展示
    """
    from reserve.relations.engine import evaluate_pair
    series_a = body.get("series_a") or {}
    series_b = body.get("series_b") or {}
    if not series_a or not series_b:
        raise HTTPException(status_code=400, detail="series_a / series_b 必填")
    model = body.get("model", "linear")
    max_lag = int(body.get("max_lag", 10))
    lag = body.get("lag")
    result = evaluate_pair(series_a, series_b, model=model, max_lag=max_lag, lag=lag)
    result["edge"] = f"{body.get('label_a', 'A')} -> {body.get('label_b', 'B')}"
    result["direction"] = result["edge"]
    return _clean(result)


@app.post("/api/v1/relations/compare", response_model=None, tags=["二次整理层"])
def api_relations_compare(body: dict):
    """实时滚动回测: 预测 vs 实际 曲线对比。

    body: {"series_a": {...}, "series_b": {...}, "model": "linear",
           "lag": null, "train_ratio": 0.7, "max_lag": 10,
           "label_a": "...", "label_b": "..."}
    """
    from reserve.relations.compare import compare
    series_a = body.get("series_a") or {}
    series_b = body.get("series_b") or {}
    if not series_a or not series_b:
        raise HTTPException(status_code=400, detail="series_a / series_b 必填")
    result = compare(series_a, series_b, model=body.get("model", "linear"),
                     lag=body.get("lag"), train_ratio=float(body.get("train_ratio", 0.7)),
                     max_lag=int(body.get("max_lag", 10)))
    result["edge"] = f"{body.get('label_a', 'A')} -> {body.get('label_b', 'B')}"
    return _clean(result)


@app.post("/api/v1/relations/run-demo", response_model=None, tags=["二次整理层"])
def api_relations_run_demo(days: int = Query(200, ge=30, le=2000),
                           model: str = Query("linear", description="评估模型"),
                           max_lag: int = Query(10, ge=1, le=30)):
    """运行内置演示: 建矩阵 + 全两两评估 + 预测对比 + 落盘。

    返回汇总 (含 Top 关联边 / 预测能力分布)。
    """
    from reserve.relations.demo import build_panel, demo_summary
    panel = build_panel(days)
    summary = demo_summary(panel, model=model, max_lag=max_lag, top=10)
    return _clean(summary)


@app.get("/api/v1/relations/network", response_model=None, tags=["二次整理层"])
def api_relations_network(min_strength: float = Query(0.1, ge=0.0, le=1.0),
                          include_comparison: bool = Query(True, description="附带预测能力评价"),
                          limit: int = Query(2000, ge=1, le=5000)):
    """传导网络分析: 节点中心性 + 强关联簇 + 网络摘要。

    站在整张关联矩阵之上回答: 谁影响全局 (枢纽)、谁被影响最多 (权威)、
    哪些品种抱团联动 (簇)、网络密度如何。
    """
    from reserve.relations.network import build_network
    store = _relation_store()
    edges = store.list_edges()
    if include_comparison:
        comps = {c.get("edge"): c for c in store.list_comparisons()}
        for e in edges:
            c = comps.get(e.get("edge"))
            if c:
                e["comparison"] = {"verdict": c.get("verdict"),
                                   "metrics": c.get("metrics")}
    net = build_network(edges, min_strength=min_strength)
    if limit and len(net["nodes"]) > limit:
        net["nodes"] = net["nodes"][:limit]
    return _clean(net)


@app.get("/api/v1/relations/paths", response_model=None, tags=["二次整理层"])
def api_relations_paths(source: Optional[str] = Query(None, description="源维度 key"),
                        target: Optional[str] = Query(None, description="目标维度 key"),
                        min_strength: float = Query(0.1, ge=0.0, le=1.0),
                        max_depth: int = Query(5, ge=2, le=8),
                        top: int = Query(5, ge=1, le=20)):
    """传导路径: 从源到目标的强传导链路 (基于有向边强度)。

    不指定 source/target 时自动选「最大枢纽 → 最大权威」。
    """
    from reserve.relations.network import strongest_paths
    store = _relation_store()
    edges = store.list_edges()
    paths = strongest_paths(edges, source=source, target=target,
                            max_depth=max_depth, min_strength=min_strength, top=top)
    return _clean({"source": source, "target": target, "count": len(paths), "paths": paths})


@app.post("/api/v1/relations/compare-models", response_model=None, tags=["二次整理层"])
def api_relations_compare_models(body: dict):
    """多模型自动对比: 同一对序列试跑多种模型, 挑预测能力最优者。

    body: {"series_a": {...}, "series_b": {...}, "models": ["linear","var",...](可选),
           "lag": null, "train_ratio": 0.7, "max_lag": 10,
           "label_a": "...", "label_b": "...",
           "from_key": "...", "to_key": "..."}   # 提供 from_key/to_key 时自动取已存序列
    """
    from reserve.relations.compare import compare_models
    series_a = body.get("series_a") or {}
    series_b = body.get("series_b") or {}
    if (not series_a or not series_b) and (body.get("from_key") and body.get("to_key")):
        store = _relation_store()
        series_a = store.load_series(body["from_key"]) or {}
        series_b = store.load_series(body["to_key"]) or {}
    if not series_a or not series_b:
        raise HTTPException(status_code=400, detail="series_a / series_b 必填 (或提供 from_key/to_key 使用已存序列)")
    result = compare_models(series_a, series_b, models=body.get("models"),
                            lag=body.get("lag"),
                            train_ratio=float(body.get("train_ratio", 0.7)),
                            max_lag=int(body.get("max_lag", 10)))
    edge = f"{body.get('label_a', 'A')} -> {body.get('label_b', 'B')}"
    if result.get("best"):
        result["best"]["edge"] = edge
    for c in result.get("comparisons", []):
        c["edge"] = edge
    return _clean(result)


@app.post("/api/v1/relations/auto-model", response_model=None, tags=["二次整理层"])
def api_relations_auto_model(body: dict):
    """对整条边自动选最优模型 (供批量/调度用)。

    body: {"series_a": {...}, "series_b": {...}, "label_a": "...", "label_b": "...",
           "max_lag": 10, "train_ratio": 0.7, "from_key": "...", "to_key": "..."}
    返回: {best_model, comparison, ranking} (只保留最优模型的预测曲线)。
    """
    from reserve.relations.compare import compare_models
    series_a = body.get("series_a") or {}
    series_b = body.get("series_b") or {}
    if (not series_a or not series_b) and (body.get("from_key") and body.get("to_key")):
        store = _relation_store()
        series_a = store.load_series(body["from_key"]) or {}
        series_b = store.load_series(body["to_key"]) or {}
    if not series_a or not series_b:
        raise HTTPException(status_code=400, detail="series_a / series_b 必填 (或提供 from_key/to_key 使用已存序列)")
    result = compare_models(series_a, series_b, lag=body.get("lag"),
                            train_ratio=float(body.get("train_ratio", 0.7)),
                            max_lag=int(body.get("max_lag", 10)))
    best = result.get("best")
    edge = f"{body.get('label_a', 'A')} -> {body.get('label_b', 'B')}"
    if best:
        best["edge"] = edge
    return _clean({"best_model": best.get("model") if best else None,
                   "best": best, "ranking": result.get("ranking", [])})



# ---------------- 兼容既有 REST API ----------------

@app.get("/api/v1/health", response_model=PublicHealth, tags=["储备库 API"])
def api_health():
    from reserve.feed import list_sources
    store = _store()
    try:
        count = store.count()
        uri = store.uri
    except Exception:
        count, uri = 0, ""
    return PublicHealth(
        status="ok",
        service="reserve-fastapi",
        version="1.0.0",
        store=str(uri),
        repo_count=count,
        sources=_clean(list_sources()),
        generated_at=_now_iso(),
    )


@app.get("/api/v1/status", response_model=None, tags=["储备库 API"])
def api_status():
    """服务状态: 储备库 + 数据源 + 信息流 一键总览 (管理台/外部监控用)。"""
    from reserve.feed import list_sources, get_feed
    store = _store()
    try:
        count = store.count()
    except Exception:
        count = 0
    feed = get_feed(mode="human", limit=5)
    return _clean({
        "ok": True,
        "service": "reserve-fastapi",
        "repo_count": count,
        "sources": list_sources(),
        "feed_today": {
            "total": feed["meta"]["total"],
            "sections": [{"key": s["key"], "title": s["title"], "count": len(s["items"])} for s in feed["sections"]],
        },
        "generated_at": _now_iso(),
    })


@app.get("/api/v1/llm/status", tags=["储备库 API"])
def api_llm_status():
    from reserve.llm import get_provider, describe_config, load_config
    p = get_provider()
    cfg = load_config()
    return _clean({
        "configured": p is not None,
        "provider": str(p) if p else None,
        "description": describe_config(),
        "config": {k: v for k, v in cfg.items() if k != "api_key"},
        "enrich_enabled": cfg.get("enrich_enabled", True),
        "review_enabled": cfg.get("review_enabled", True),
    })


@app.get("/api/v1/dashboard/overview", tags=["储备库 API"])
def api_dashboard_overview(days: int = 7):
    from reserve.dashboard import overview
    return _clean(overview(store=_store(), days=days))


@app.get("/api/v1/dashboard/repos", tags=["储备库 API"])
def api_dashboard_repos(
    decision: Optional[str] = None, category: Optional[str] = None,
    tag: Optional[str] = None, q: Optional[str] = None,
    limit: int = 50, offset: int = 0, sort: str = "stars",
):
    from reserve.dashboard import repos_view
    return _clean(repos_view(store=_store(), decision=decision, category=category,
                             tag=tag, q=q, limit=limit, offset=offset, sort=sort))


@app.get("/api/v1/dashboard/clusters", tags=["储备库 API"])
def api_dashboard_clusters(mode: str = "by-tags", k: int = 6):
    from reserve.dashboard import clusters_view
    return _clean(clusters_view(store=_store(), mode=mode, k=k))


@app.get("/api/v1/dashboard/snapshots", tags=["储备库 API"])
def api_dashboard_snapshots(days: int = 14):
    from reserve.dashboard import snapshots_view
    return _clean(snapshots_view(days=days, store=_store()))


@app.get("/api/v1/dashboard/needs", tags=["储备库 API"])
def api_dashboard_needs():
    from reserve.dashboard import needs_view
    return _clean(needs_view(store=_store()))


@app.get("/api/v1/dashboard/review", tags=["储备库 API"])
def api_dashboard_review():
    from reserve.dashboard import review_view
    return _clean(review_view())


@app.get("/api/v1/quality", tags=["储备库 API"])
def api_quality(days: int = 7):
    from reserve.quality import build_report
    return _clean(build_report(days=days, store=_store()))


@app.get("/api/v1/quality/trend", tags=["储备库 API"])
def api_quality_trend(days: int = 7):
    from reserve.quality import assess_trend
    return _clean(assess_trend(days=days))


@app.get("/api/v1/quality/snapshot", tags=["储备库 API"])
def api_quality_snapshot(path: Optional[str] = None):
    from reserve.quality import assess_snapshot
    if path:
        return _clean(assess_snapshot(path))
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = ROOT / "pipeline" / "data" / "snapshots" / f"{today}.json"
    if not p.exists():
        snaps = sorted((ROOT / "pipeline" / "data" / "snapshots").glob("*.json"), reverse=True)
        p = snaps[0] if snaps else p
    return _clean(assess_snapshot(p))


@app.get("/api/v1/reserve/repos", tags=["储备库 API"])
def api_reserve_repos(decision: Optional[str] = None, category: Optional[str] = None,
                      tag: Optional[str] = None, limit: int = 50):
    store = _store()
    where = None
    filters = []
    if decision:
        filters.append(f"category_decision = '{decision}'")
    if category:
        filters.append(f"category = '{category}'")
    if tag:
        filters.append(f"function_tags LIKE '%{tag}%'")
    if filters:
        where = " AND ".join(filters)
    rows = store.query(where=where, limit=limit)
    return {"count": len(rows), "items": _clean(rows)}


@app.get("/api/v1/reserve/repos/{full_name:path}", tags=["储备库 API"])
def api_reserve_repo_detail(full_name: str):
    repo = _store().get_repo(full_name)
    if repo is None:
        raise HTTPException(status_code=404, detail="not found")
    return _clean(repo)


@app.get("/api/v1/search", tags=["储备库 API"])
def api_search(q: str, top: int = 10, mode: str = "hybrid", decision: Optional[str] = None):
    from reserve.search import search
    results = search(q, top_k=top, mode=mode, decision=decision, store=_store())
    return {"query": q, "count": len(results), "items": _clean(results)}


@app.get("/api/v1/needs", tags=["储备库 API"])
def api_needs():
    return {"needs": _clean(_store().needs_get())}


@app.post("/api/v1/reserve/match", tags=["储备库 API"])
def api_reserve_match(body: MatchBody):
    from reserve.search import search
    q = body.query or body.q or body.text
    if not q:
        raise HTTPException(status_code=400, detail="query required")
    results = search(q, top_k=body.top, store=_store(), decision=body.decision)
    return {"query": q, "count": len(results), "items": _clean(results)}


@app.post("/api/v1/reserve/trigger", tags=["储备库 API"])
def api_reserve_trigger(body: TriggerBody):
    from reserve.trigger import trigger
    q = body.query or body.text
    if not q:
        raise HTTPException(status_code=400, detail="query required")
    res = trigger(q, top_k=body.top, store=_store(), decision_filter=body.decision)
    return _clean(res)


@app.post("/api/v1/needs/rematch", tags=["储备库 API"])
def api_needs_rematch():
    from reserve.trigger import rematch_pending_needs
    results = rematch_pending_needs(_store())
    return {"matched": len(results), "results": _clean(results)}


@app.get("/api/v1/review/queue", tags=["储备库 API"])
def api_review_queue(status: Optional[str] = None):
    from reserve.review import queue_list
    q = queue_list()
    if status:
        q = [e for e in q if e.get("status") == status]
    return {"count": len(q), "items": _clean(q)}


@app.put("/api/v1/review/queue", tags=["储备库 API"])
def api_review_queue_update(name: str, status: str = "approved", note: str = "", reviewer: str = "api"):
    from reserve.review import queue_update
    if status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be approved/rejected")
    entry = queue_update(name, status, note=note, reviewer=reviewer)
    if entry is None:
        raise HTTPException(status_code=404, detail="not found")
    return _clean(entry)


@app.get("/api/v1/heal/log", tags=["储备库 API"])
def api_heal_log(limit: int = 50):
    from reserve.self_heal import IncidentLog
    return {"incidents": _clean(IncidentLog().list(limit=limit))}


@app.post("/api/v1/heal", tags=["储备库 API"])
def api_heal(body: HealBody | None = None):
    from reserve.self_heal import run_self_heal
    body = body or HealBody()
    result = run_self_heal(check_only=body.check_only, store=_store(), verbose=False)
    return _clean(result)


@app.post("/api/v1/review/run", tags=["储备库 API"])
def api_review_run():
    from reserve.review import review_action_candidates
    store = _store()
    repos = store.all_repos(limit=100)
    candidates = [r for r in repos if r.get("category_decision") == "action"
                  and r.get("review_status") != "approved"]
    review_action_candidates(candidates, fetch_readme=False)
    return {"queued": len(candidates)}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="FastAPI 聚合管理 + 对外信息流")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"[fastapi] listening on http://{args.host}:{args.port}")
    print("[fastapi] 管理页面: http://127.0.0.1:8000/")
    print("[fastapi] 对外信息流: GET /api/v1/feed?mode=human|ai")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
