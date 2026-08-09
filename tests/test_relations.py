"""二次整理层 (reserve/relations) 测试 —— 两两关联量化 + 预测能力验证。

覆盖:
  - dims: 维度解析 / 通配匹配 / 标签
  - frame: 两两有序对 (方向敏感, 排除自环)
  - engine: 各模型评估 / 方向不对称 / 强度范围
  - compare: 预测 vs 实际 曲线 / 指标 / verdict
  - store: 持久化
  - demo: 端到端 (还原真实传导结构)
  - fastapi: 路由注册
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reserve.relations.dims import parse_dim, Dim, dim_label
from reserve.relations.frame import expand_targets, ordered_pairs, build_matrix, pair_key
from reserve.relations.engine import (evaluate_pair, evaluate_all, returns,
                                      align_series, lead_lag, _prepare_pair, resample_daily)
from reserve.relations.compare import compare, predict_impact
from reserve.relations.store import RelationStore
from reserve.relations.demo import build_panel, demo_summary


# ---------- dims ----------

def test_parse_dim_full():
    d = parse_dim("futures.CN.SHFE.CU.futures.1d")
    assert d.market == "futures"
    assert d.symbol == "CU"
    assert d.country == "CN"
    assert d.exchange == "SHFE"
    assert d.asset == "futures"
    assert d.timeframe == "1d"


def test_parse_dim_defaults():
    d = parse_dim("futures.CU")
    assert d.market == "futures" and d.symbol == "CU"
    assert d.country == "*" and d.exchange == "*" and d.asset == "*" and d.timeframe == "*"


def test_dim_matches_wildcard():
    a = parse_dim("futures.*.*.CU.*.1d")
    b = parse_dim("futures.CN.SHFE.CU.futures.1d")
    assert a.matches(b)
    c = parse_dim("equity.CN.SSE.CU.spot.1d")
    assert not a.matches(c)


def test_dim_label():
    d = parse_dim("futures.CN.SHFE.CU.futures.1d")
    assert "CU" in dim_label(d)
    assert "期货" in dim_label(d) or "合约" in dim_label(d)


# ---------- frame ----------

def test_ordered_pairs_directional():
    targets = ["equity.CN.SSE.000300.index.1d", "equity.CN.SSE.000300.etf.1d"]
    pairs = ordered_pairs(targets)
    assert len(pairs) == 2  # 2 维 -> 2 条有向边 (排除自环)
    keys = {pair_key(a, b) for a, b in pairs}
    assert "equity.CN.SSE.000300.index.1d -> equity.CN.SSE.000300.etf.1d" in keys
    assert "equity.CN.SSE.000300.etf.1d -> equity.CN.SSE.000300.index.1d" in keys


def test_build_matrix_counts():
    m = build_matrix(["a.*.*.X.*.1d", "b.*.*.Y.*.1d", "c.*.*.Z.*.1d"])
    assert m["pair_count"] == 6  # 3 维 -> 3*2 = 6 条
    assert len(m["pairs"]) == 6
    assert m["schema_version"] == "1.0"


# ---------- engine ----------

def _two_series(n=120, beta=0.5, lag=1, seed=7):
    """构造 A 领先影响 B 的两条序列。"""
    import random
    rng = random.Random(seed)
    a, b = {}, {}
    pa = pb = 100.0
    dates = []
    from datetime import datetime, timedelta, timezone
    day = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        dates.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    for i, d in enumerate(dates):
        ra = rng.gauss(0, 0.01)
        pa = pa * (1 + ra)
        a[d] = pa
        rb = rng.gauss(0, 0.01)
        if i >= lag:
            rb += beta * ra
        pb = pb * (1 + rb)
        b[d] = pb
    return a, b


def test_evaluate_linear_detects_influence():
    a, b = _two_series(beta=0.5, lag=1)
    res = evaluate_pair(a, b, model="linear", max_lag=5)
    assert res["strength"] > 0.1
    assert res["insufficient_data"] is False
    assert 0.0 <= res["strength"] <= 1.0
    assert res["model"] == "linear"
    assert "r2" in res["metrics"]


def test_evaluate_directional_asymmetry():
    """方向敏感: 构造 A 影响 B, 则 A→B 与 B→A 强度应不同 (至少存在 lag 差异)。"""
    a, b = _two_series(beta=0.8, lag=2)
    ab = evaluate_pair(a, b, model="lead_lag", max_lag=6)
    ba = evaluate_pair(b, a, model="lead_lag", max_lag=6)
    # A 领先 B: A→B 的 lag 应为正, B→A 的 lag 应为负
    assert ab["lag"] >= 0
    assert ba["lag"] <= 0


def test_models_all_run():
    a, b = _two_series(beta=0.5, lag=1)
    for model in ("correlation", "lead_lag", "vol_spillover", "linear", "momentum", "exp_decay", "var"):
        res = evaluate_pair(a, b, model=model, max_lag=5)
        assert res["model"] == model
        assert 0.0 <= res.get("strength", 0) <= 1.0


def test_insufficient_data():
    res = evaluate_pair({"2026-01-01": 1.0, "2026-01-02": 1.1}, {"2026-01-01": 5.0, "2026-01-02": 5.2},
                        model="linear")
    assert res["insufficient_data"] is True


def test_resample_daily():
    s = {"2026-01-01T06:00": 10.0, "2026-01-01T10:00": 14.0, "2026-01-02T06:00": 20.0}
    daily = resample_daily(s)
    assert daily["2026-01-01"] == 12.0
    assert daily["2026-01-02"] == 20.0


def test_cross_timeframe_auto_resample():
    """BTC 4h 与 日线序列无共同日期时, 自动重采样对齐。"""
    daily = {"2026-01-01": 100.0, "2026-01-02": 101.0, "2026-01-03": 102.0}
    intraday = {"2026-01-01T00:00": 10.0, "2026-01-01T04:00": 12.0,
                "2026-01-02T00:00": 11.0, "2026-01-02T04:00": 13.0}
    sa, sb, resampled = _prepare_pair(daily, intraday)
    assert resampled is True
    assert set(sa) & set(sb)  # 对齐后有交集


# ---------- compare ----------

def test_compare_metrics_and_verdict():
    a, b = _two_series(beta=0.7, lag=1, n=150)
    res = compare(a, b, model="linear", max_lag=5)
    assert res["test_size"] > 0
    assert len(res["curve"]["dates"]) == res["test_size"]
    assert len(res["curve"]["actual"]) == len(res["curve"]["predicted"])
    assert res["metrics"]["r2"] >= 0.0
    assert "rmse" in res["metrics"]
    assert "hit_rate" in res["metrics"]
    assert res["verdict"] in ("strong", "good", "weak", "insufficient")
    assert res["iterations"]  # 有迭代建议


def test_compare_insufficient():
    res = compare({"a": 1.0}, {"b": 2.0}, model="linear")
    assert res["verdict"] == "insufficient"


def test_predict_impact_shape():
    a, b = _two_series(n=60)
    params = {"a": 0.0, "b": 0.4, "c": 0.0}
    curve = predict_impact(a, b, params, lag=1)
    assert len(curve["dates"]) == len(curve["actual"]) == len(curve["predicted"]) == len(curve["residual"])
    assert len(curve["dates"]) > 0


# ---------- store ----------

def test_store_roundtrip(tmp_path):
    store = RelationStore(tmp_path)
    edge = {"edge": "A -> B", "strength": 0.7, "model": "linear"}
    store.save_edge(edge)
    assert store.load_edge("A -> B")["strength"] == 0.7
    assert store.count_edges() == 1
    store.save_matrix({"dimensions": [], "pair_count": 0})
    assert store.load_matrix()["pair_count"] == 0
    store.save_comparison("A -> B", {"verdict": "good", "metrics": {"r2": 0.4}})
    assert store.load_comparison("A -> B")["verdict"] == "good"


# ---------- demo (端到端) ----------

def test_demo_build_panel():
    panel = build_panel(days=60)
    assert len(panel) == 8
    assert "macro.global.MACRO.US10Y.rate.1d" in panel


def test_demo_summary_recovers_structure():
    """端到端: 演示数据应还原「同品种不同交易类型」最强关联 + 预测对比可用。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["RELATION_DIR"] = td
        panel = build_panel(days=150)
        summary = demo_summary(panel, model="linear", max_lag=8, top=5)
        os.environ.pop("RELATION_DIR", None)
        assert summary["edge_count"] == 8 * 7  # 8 维 -> 56 条有向边
        top = summary["top_strength"][0]
        # 同品种不同交易类型 (000300 指数 <-> ETF) 应排最前
        assert "000300" in top["from"]["symbol"] or "000300" in top["to"]["symbol"]
        assert summary["top_verdict"]  # 有预测能力排序
        # 预测能力分布存在
        dist = {}
        for c in summary["comparisons"]:
            dist[c["verdict"]] = dist.get(c["verdict"], 0) + 1
        assert sum(dist.values()) == 56


# ---------- fastapi 路由 ----------

def test_fastapi_relations_routes():
    from reserve.fastapi_app import app
    paths = {getattr(r, "path", "") for r in app.routes if hasattr(r, "path")}
    for route in ("/api/v1/relations/matrix", "/api/v1/relations/edges",
                  "/api/v1/relations/edge/{edge:path}", "/api/v1/relations/comparisons",
                  "/api/v1/relations/evaluate", "/api/v1/relations/compare",
                  "/api/v1/relations/run-demo"):
        assert route in paths, f"missing fastapi route: {route}"


def test_api_relations_evaluate_endpoint():
    """通过 TestClient 验证实时评估接口 (需 fastapi testclient)。"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return  # 无 testclient 依赖时跳过
    from reserve.fastapi_app import app
    a, b = _two_series(n=60, beta=0.5, lag=1)
    client = TestClient(app)
    resp = client.post("/api/v1/relations/evaluate", json={
        "series_a": a, "series_b": b, "model": "linear", "label_a": "A", "label_b": "B",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["edge"] == "A -> B"
    assert 0.0 <= data["strength"] <= 1.0


def test_api_relations_compare_endpoint():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return
    from reserve.fastapi_app import app
    a, b = _two_series(n=100, beta=0.6, lag=1)
    client = TestClient(app)
    resp = client.post("/api/v1/relations/compare", json={
        "series_a": a, "series_b": b, "model": "linear",
        "label_a": "A", "label_b": "B",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data and "verdict" in data
    assert data["edge"] == "A -> B"
