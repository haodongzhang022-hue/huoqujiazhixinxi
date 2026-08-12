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


# ---------- 分层漏斗 (功能域分层) ----------

def test_layers_funnel_definition():
    """功能域分层漏斗: 6 层按深度升序, 每层对应一个 Dim 字段。"""
    from reserve.relations.dims import layers, funnel_depth
    ls = layers()
    # 漏斗: 资产大类 -> 地区 -> 交易所 -> 品种 -> 交易类型 -> 时间级别
    assert [l["id"] for l in ls] == [
        "data_class", "region", "exchange", "instrument", "trade_type", "time_level"]
    # 深度递增
    assert [l["order"] for l in ls] == [0, 1, 2, 3, 4, 5]
    assert funnel_depth("market") == 0   # 资产大类在最顶
    assert funnel_depth("timeframe") == 5  # 时间级别在最底


def test_dim_funnel_path():
    """维度能展开成分层漏斗路径。"""
    d = parse_dim("futures.CN.SHFE.CU.futures.1d")
    p = d.path()
    assert p[0].startswith("资产大类:futures")
    assert any(x.startswith("品种:CU") for x in p)
    assert p[-1].startswith("时间级别:1d")
    # 未指定的层不出现
    assert len(parse_dim("futures.CU").path()) == 2


def test_relationship_intra_vs_inter_layer():
    """层内 vs 层间判定: 同一资产大类=层内, 跨资产大类=层间。"""
    from reserve.relations.dims import relationship_kind
    a = parse_dim("equity.CN.SSE.000300.index.1d")
    # 同品种不同交易类型 -> 层内 (同功能域分支内部联动)
    b = parse_dim("equity.CN.SSE.000300.etf.1d")
    assert relationship_kind(a, b)["kind"] == "intra_layer"
    # 同品种不同时间级别 -> 层内
    c = parse_dim("crypto.global.CRYPTO.BTC.spot.4h")
    d = parse_dim("crypto.global.CRYPTO.BTC.spot.1d")
    assert relationship_kind(c, d)["kind"] == "intra_layer"
    # 同大类不同地区 -> 层内
    assert relationship_kind(parse_dim("equity.CN"), parse_dim("equity.US"))["kind"] == "intra_layer"
    # 跨资产大类 (股票 vs 期货) -> 层间
    e = parse_dim("futures.CN.SHFE.CU.futures.1d")
    assert relationship_kind(a, e)["kind"] == "inter_layer"
    # 宏观利率 -> 股票 -> 层间
    macro = parse_dim("macro.global.MACRO.US10Y.rate.1d")
    assert relationship_kind(macro, a)["kind"] == "inter_layer"
    # 自环
    assert relationship_kind(a, a)["kind"] == "same_node"


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


def test_lead_lag_negative_lag_no_crash():
    """回归: lead_lag 在最佳 lag 为负 (B 领先 A) 时不应崩溃。

    修复前 _lagged 会把负 lag 直接传入导致 dates[pi] 越界 IndexError;
    _stability 同样对负 lag 交换 A/B 再算。
    """
    a, b = _two_series(beta=0.8, lag=2)
    # B 领先 A 的场景: B→A 应得到负 lag 且不抛异常
    res = evaluate_pair(b, a, model="lead_lag", max_lag=6)
    assert res["model"] == "lead_lag"
    assert 0.0 <= res["strength"] <= 1.0
    assert "stability" in res and 0.0 <= res["stability"] <= 1.0
    # 演示面板跨维度评估也不应因负 lag 崩溃
    from reserve.relations.demo import build_panel
    from reserve.relations.engine import evaluate_all
    panel = build_panel(days=120)
    results = evaluate_all(panel, model="lead_lag", max_lag=5)
    assert len(results) == 56


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
                  "/api/v1/relations/run-demo", "/api/v1/relations/network",
                  "/api/v1/relations/paths", "/api/v1/relations/compare-models",
                  "/api/v1/relations/auto-model"):
        assert route in paths, f"missing fastapi route: {route}"


# ---------- 新增: 时变关联 / 结构突变 / 事件研究 / 自相关 (ISSUE #7 第二轮) ----------

def test_new_models_all_run():
    a, b = _two_series(beta=0.5, lag=1, n=150)
    for model in ("rolling_corr", "regime_shift", "event_study", "self_corr"):
        res = evaluate_pair(a, b, model=model, max_lag=5)
        assert res["model"] == model
        assert 0.0 <= res.get("strength", 0) <= 1.0
        assert "metrics" in res


def test_rolling_corr_variable_curve():
    """滚动相关应产出时变曲线 (关联强度是变量, 不是固定值)。"""
    a, b = _two_series(beta=0.5, lag=1, n=200)
    res = evaluate_pair(a, b, model="rolling_corr", max_lag=5)
    assert "curve" in res and len(res["curve"]) >= 10
    assert "mean_corr" in res["params"] and "std" in res["params"]
    assert all(0 <= abs(p["corr"]) <= 1 for p in res["curve"])


def test_regime_shift_detects_reversal():
    """构造前后两段符号相反的关系, 应检出 reverse 突变。"""
    import random
    from datetime import datetime, timedelta, timezone
    rng = random.Random(11)
    a, b = {}, {}
    pa = pb = 100.0
    dates = []
    day = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(120):
        dates.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    for i, d in enumerate(dates):
        ra = rng.gauss(0, 0.01)
        pa *= (1 + ra)
        a[d] = pa
        beta = 0.6 if i < 60 else -0.6  # 前段正相关, 后段负相关
        rb = rng.gauss(0, 0.01) + beta * ra
        pb *= (1 + rb)
        b[d] = pb
    res = evaluate_pair(a, b, model="regime_shift", max_lag=5)
    assert res["metrics"]["shift_type"] in ("reverse", "weaken")
    assert res["params"]["break_date"] is not None


def test_event_study_finds_events():
    a, b = _two_series(beta=0.7, lag=1, n=200)
    res = evaluate_pair(a, b, model="event_study", max_lag=5)
    assert res["metrics"]["event_count"] > 0
    assert "hit_rate" in res["metrics"]


def test_self_corr_basic():
    from reserve.relations.engine import self_corr
    a, _ = _two_series(beta=0.5, lag=1, n=150)
    sc = self_corr(a, max_lag=5)
    assert 0.0 <= sc["strength"] <= 1.0
    assert "lag1_ac" in sc


# ---------- 新增: 传导网络 (network) ----------

def test_network_build():
    from reserve.relations.network import build_network
    from reserve.relations.demo import build_panel
    from reserve.relations.engine import evaluate_all
    panel = build_panel(days=120)
    results = evaluate_all(panel, model="linear", max_lag=5)
    net = build_network(results, min_strength=0.02)
    assert net["nodes"]
    assert net["edges"]
    assert "summary" in net
    assert net["summary"]["node_count"] >= 2
    assert net["summary"]["top_hubs"]
    # 分层漏斗: 边带层内/层间标记, 节点带功能域归属
    assert "intra_layer_edges" in net["summary"]
    assert "inter_layer_edges" in net["summary"]
    assert any("relation_kind" in e for e in net["edges"])
    assert all("funnel" in n for n in net["nodes"])
    assert "layer_groups" in net and net["layer_groups"]
    # 演示数据应同时存在层内(同品种不同交易类型/时间级别)与层间(跨资产大类)边
    kinds = {e["relation_kind"] for e in net["edges"]}
    assert "intra_layer" in kinds and "inter_layer" in kinds


def test_strongest_paths():
    from reserve.relations.network import strongest_paths
    # 链式: A -> M -> B, 验证路径还原
    edges = [
        {"edge": "A -> M", "from": {"market": "a", "symbol": "A"},
         "to": {"market": "m", "symbol": "M"}, "strength": 0.6},
        {"edge": "M -> B", "from": {"market": "m", "symbol": "M"},
         "to": {"market": "b", "symbol": "B"}, "strength": 0.7},
        {"edge": "A -> B", "from": {"market": "a", "symbol": "A"},
         "to": {"market": "b", "symbol": "B"}, "strength": 0.3},
    ]
    paths = strongest_paths(edges, source="a.*.*.A.*.*", target="b.*.*.B.*.*",
                            max_depth=4, min_strength=0.05)
    assert paths
    assert paths[0]["length"] >= 1


def test_network_summary_shape():
    from reserve.relations.network import network_summary
    from reserve.relations.demo import build_panel
    from reserve.relations.engine import evaluate_all
    panel = build_panel(days=100)
    results = evaluate_all(panel, model="linear", max_lag=5)
    s = network_summary(results, min_strength=0.02)
    assert s["nodes"] >= 2
    assert "top_hubs" in s and "top_authorities" in s and "strongest_link" in s


# ---------- 新增: 多模型对比 (compare_models) ----------

def test_compare_models_picks_best():
    from reserve.relations.compare import compare_models
    a, b = _two_series(beta=0.7, lag=1, n=180)
    res = compare_models(a, b, models=["linear", "momentum", "exp_decay", "var"])
    assert res["best"] is not None
    assert res["ranking"]
    assert res["best"]["model"] == res["ranking"][0]["model"]
    assert res["ranking"][0]["score"] >= res["ranking"][-1]["score"]


# ---------- 新增: store 序列快照 ----------

def test_store_series_roundtrip(tmp_path):
    store = RelationStore(tmp_path)
    store.save_series("equity.CN.SSE.000300.index.1d", {"2026-01-01": 1.0, "2026-01-02": 2.0})
    assert store.load_series("equity.CN.SSE.000300.index.1d")["2026-01-01"] == 1.0
    assert "equity.CN.SSE.000300.index.1d" in store.list_series_keys()


# ---------- 新增: 新端点 E2E ----------

def test_api_relations_network_endpoint():
    """传导网络端点: 基于已落盘边数据构建网络。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["RELATION_DIR"] = td
        try:
            from reserve.relations.demo import build_panel, demo_summary
            panel = build_panel(days=80)
            demo_summary(panel, model="linear", max_lag=4, top=3)
            from fastapi.testclient import TestClient
            from reserve.fastapi_app import app
            client = TestClient(app)
            resp = client.get("/api/v1/relations/network?min_strength=0.02")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nodes"]
            assert data["summary"]["node_count"] >= 2
            assert "clusters" in data
            # 分层漏斗: 网络应带层内/层间边统计
            assert "intra_layer_edges" in data["summary"]
            assert "inter_layer_edges" in data["summary"]
        finally:
            os.environ.pop("RELATION_DIR", None)


def test_api_relations_edges_layer_filter():
    """边列表端点: 按层内/层间(rel)筛选多级漏斗。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["RELATION_DIR"] = td
        try:
            from reserve.relations.demo import build_panel, demo_summary
            panel = build_panel(days=80)
            demo_summary(panel, model="linear", max_lag=4, top=3)
            from fastapi.testclient import TestClient
            from reserve.fastapi_app import app
            client = TestClient(app)
            r = client.get("/api/v1/relations/edges?limit=100")
            assert r.status_code == 200
            assert r.json()["count"] > 0
            # 层内筛选
            r_intra = client.get("/api/v1/relations/edges?limit=100&rel=intra_layer")
            intra = r_intra.json()
            assert intra["count"] > 0
            assert all(e["relation_kind"] == "intra_layer" for e in intra["items"])
            # 层间筛选
            r_inter = client.get("/api/v1/relations/edges?limit=100&rel=inter_layer")
            inter = r_inter.json()
            assert inter["count"] > 0
            assert all(e["relation_kind"] == "inter_layer" for e in inter["items"])
            # 两者之和应等于总数(无重叠)
            assert intra["count"] + inter["count"] == r.json()["count"]
        finally:
            os.environ.pop("RELATION_DIR", None)


def test_api_relations_compare_models_with_keys():
    """多模型对比端点: 通过 from_key/to_key 自动取已存序列。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["RELATION_DIR"] = td
        try:
            from reserve.relations.demo import build_panel, demo_summary
            panel = build_panel(days=80)
            demo_summary(panel, model="linear", max_lag=4, top=3)
            from fastapi.testclient import TestClient
            from reserve.fastapi_app import app
            client = TestClient(app)
            edges = client.get("/api/v1/relations/edges?limit=2").json()["items"]
            e = edges[0]
            fk = ".".join([e["from"][k] for k in ("market", "country", "exchange", "symbol", "asset", "timeframe")])
            tk = ".".join([e["to"][k] for k in ("market", "country", "exchange", "symbol", "asset", "timeframe")])
            resp = client.post("/api/v1/relations/compare-models",
                               json={"from_key": fk, "to_key": tk})
            assert resp.status_code == 200
            data = resp.json()
            assert data["best"] is not None
            assert len(data["ranking"]) >= 1
        finally:
            os.environ.pop("RELATION_DIR", None)


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
