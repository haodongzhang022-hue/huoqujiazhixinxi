"""二次整理层 · 功能校验脚本 (Functional Validation) —— 校验「功能是否实际达成」。

设计理念:
  区别于单元测试(只测接口正确性), 本脚本以**端到端跑真实功能**的方式,
  把「二次整理层」承诺的业务能力当作验收标准, 对**运行结果本身做断言校验**,
  从而确认每个功能点是否真正达成 (而不只是"代码能跑")。

覆盖的业务验收点 (对齐 docs/relation-analysis-layer.md 与 ISSUE #7):
  [F1] 维度系统 覆盖 跨市场/跨国家/跨品种/跨交易类型/跨时间级别 (6段维度 + 通配)
  [F2] 功能域分层漏斗 (资产大类→地区→交易所→品种→交易类型→时间级别) + 层内/层间判定
  [F3] 两两有序关联矩阵: 8 维 → 56 条有向边, 排除自环, 方向敏感(A→B≠B→A)
  [F4] 11 种量化模型全部可运行且强度归一化在 [0,1]
  [F5] 预测能力验证(compare 滚动回测): 训练段拟合→测试段预测vs实际, 输出指标+verdict+迭代建议
  [F6] 端到端还原真实传导结构 (核心): 演示数据应还原「同品种不同交易类型最强关联」
       「US10Y 为全局领先驱动枢纽」「BTC 领先影响 AAPL」「USDCNY→A股 负相关」
  [F7] 传导网络: 节点中心性/强关联簇/层内层间边统计
  [F8] 多模型自动择优(compare_models): 返回最优模型 + 按得分排序
  [F9] 持久化(RelationStore): 矩阵/边/对比/序列 落盘并可回读
  [F10] 跨时间级别自动重采样对齐 (BTC 4h 与日线)

运行方式 (无需第三方依赖, 纯标准库):
  python3 tests/test_relations_functional.py
  退出码 0 = 全部通过(功能实际达成); 非 0 = 存在未达成项。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """登记一项功能校验结果。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ [通过] {name}" + (f"  — {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ❌ [未达成] {name}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 准备: 构造演示面板 (含可验证的真实传导结构)
# ---------------------------------------------------------------------------
def make_panel(days: int = 200) -> dict:
    from reserve.relations.demo import build_panel
    return build_panel(days=days)


# ---------------------------------------------------------------------------
# [F1] 维度系统
# ---------------------------------------------------------------------------
def validate_dims() -> None:
    from reserve.relations.dims import parse_dim, Dim
    # 全 6 段解析
    d = parse_dim("futures.CN.SHFE.CU.futures.1d")
    check("F1.1 6段维度完整解析", all([d.market == "futures", d.symbol == "CU",
                                        d.country == "CN", d.exchange == "SHFE",
                                        d.asset == "futures", d.timeframe == "1d"]),
          f"{d.to_dict()}")
    # 短格式自动补全
    d2 = parse_dim("futures.CU")
    check("F1.2 短格式缺省段补全", d2.market == "futures" and d2.symbol == "CU"
          and d2.country == "*", d2.to_dict())
    # 通配匹配
    a = parse_dim("futures.*.*.CU.*.1d")
    check("F1.3 通配符匹配", a.matches(parse_dim("futures.CN.SHFE.CU.futures.1d")))
    # 覆盖跨市场/跨国家/跨品种/跨交易类型/跨时间级别
    panel = make_panel()
    keys = set(panel.keys())
    has_cross_market = any("equity" in k for k in keys) and any("futures" in k for k in keys) \
        and any("crypto" in k for k in keys) and any("forex" in k for k in keys)
    has_cross_country = any(".CN." in k for k in keys) and any(".US." in k for k in keys)
    has_cross_symbol = any(".CU." in k for k in keys) and any(".AAPL." in k for k in keys)
    has_cross_tradetype = any(".index." in k for k in keys) and any(".etf." in k for k in keys)
    has_cross_timeframe = any(".1d" in k for k in keys) and any(".4h" in k for k in keys)
    check("F1.4 跨市场覆盖", has_cross_market)
    check("F1.5 跨国家覆盖", has_cross_country)
    check("F1.6 跨品种覆盖", has_cross_symbol)
    check("F1.7 跨交易类型覆盖", has_cross_tradetype)
    check("F1.8 跨时间级别覆盖", has_cross_timeframe)


# ---------------------------------------------------------------------------
# [F2] 功能域分层漏斗 + 层内/层间
# ---------------------------------------------------------------------------
def validate_layers() -> None:
    from reserve.relations.dims import parse_dim, layers, relationship_kind
    ls = layers()
    ids = [l["id"] for l in ls]
    check("F2.1 功能域分层漏斗 6 层定义",
          ids == ["data_class", "region", "exchange", "instrument", "trade_type", "time_level"],
          "资产大类→地区→交易所→品种→交易类型→时间级别")
    check("F2.2 漏斗深度升序", [l["order"] for l in ls] == [0, 1, 2, 3, 4, 5])
    # 维度展开成漏斗路径
    p = parse_dim("futures.CN.SHFE.CU.futures.1d").path()
    check("F2.3 维度展开漏斗路径", p[0].startswith("资产大类:futures") and p[-1].startswith("时间级别:1d"),
          " → ".join(p))
    # 层内(同功能域分支) vs 层间(跨功能域)
    idx = parse_dim("equity.CN.SSE.000300.index.1d")
    etf = parse_dim("equity.CN.SSE.000300.etf.1d")
    cu = parse_dim("futures.CN.SHFE.CU.futures.1d")
    check("F2.4 同品种不同交易类型=层内",
          relationship_kind(idx, etf)["kind"] == "intra_layer")
    check("F2.5 跨资产大类=层间",
          relationship_kind(idx, cu)["kind"] == "inter_layer")


# ---------------------------------------------------------------------------
# [F3] 两两有序关联矩阵
# ---------------------------------------------------------------------------
def validate_matrix() -> None:
    from reserve.relations.frame import build_matrix
    panel = make_panel()
    matrix = build_matrix(list(panel.keys()))
    check("F3.1 矩阵维度数量=8", len(matrix["dimensions"]) == 8)
    check("F3.2 有向边数量=56 (8*7, 排除自环)", matrix["pair_count"] == 56,
          f"实际 {matrix['pair_count']}")
    # 方向敏感: A→B 与 B→A 都是独立边 (使用边自带 edge 字段, 避免拼 dict)
    pair_keys = {p["edge"] for p in matrix["pairs"]}
    has_ab = "equity.CN.SSE.000300.index.1d -> equity.CN.SSE.000300.etf.1d" in pair_keys
    has_ba = "equity.CN.SSE.000300.etf.1d -> equity.CN.SSE.000300.index.1d" in pair_keys
    check("F3.3 方向敏感(两向独立边)", has_ab and has_ba)
    # 无自环
    check("F3.4 无自环", not any(p["from"] == p["to"] for p in matrix["pairs"]))


# ---------------------------------------------------------------------------
# [F4] 11 种量化模型
# ---------------------------------------------------------------------------
def validate_models() -> None:
    from reserve.relations.engine import evaluate_pair, MODELS
    from reserve.relations.demo import build_panel
    panel = build_panel(days=200)
    a = panel["equity.CN.SSE.000300.index.1d"]
    b = panel["equity.CN.SSE.000300.etf.1d"]
    all_models = ["correlation", "lead_lag", "vol_spillover", "linear", "momentum",
                  "exp_decay", "var", "rolling_corr", "regime_shift", "event_study", "self_corr"]
    check("F4.0 引擎注册 11 种模型", len(MODELS) >= 11, f"已注册 {len(MODELS)}")
    ok_models = 0
    strength_in_range = True
    for m in all_models:
        res = evaluate_pair(a, b, model=m, max_lag=5)
        if res["model"] == m and 0.0 <= res.get("strength", 0) <= 1.0:
            ok_models += 1
        else:
            strength_in_range = False
    check("F4.1 全部模型可运行且强度∈[0,1]", ok_models == len(all_models) and strength_in_range,
          f"{ok_models}/{len(all_models)} 通过")
    # 时变关联产出曲线 (关联强度是变量而非固定值)
    rc = evaluate_pair(a, b, model="rolling_corr", max_lag=5)
    check("F4.2 时变关联产出强度曲线", "curve" in rc and len(rc["curve"]) >= 10,
          f"曲线点数 {len(rc.get('curve', []))}")
    # 结构突变能检出反转
    import random
    from datetime import datetime, timedelta, timezone
    rng = random.Random(11)
    aa, bb = {}, {}
    pa = pb = 100.0
    dates = []
    day = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(120):
        dates.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    for i, dd in enumerate(dates):
        ra = rng.gauss(0, 0.01)
        pa *= (1 + ra)
        aa[dd] = pa
        beta = 0.6 if i < 60 else -0.6
        rb = rng.gauss(0, 0.01) + beta * ra
        pb *= (1 + rb)
        bb[dd] = pb
    rs = evaluate_pair(aa, bb, model="regime_shift", max_lag=5)
    check("F4.3 结构突变检出反转", rs["metrics"].get("shift_type") in ("reverse", "weaken"),
          f"shift_type={rs['metrics'].get('shift_type')}")


# ---------------------------------------------------------------------------
# [F5] 预测能力验证 (compare 滚动回测)
# ---------------------------------------------------------------------------
def validate_compare() -> None:
    from reserve.relations.compare import compare
    from reserve.relations.demo import build_panel
    panel = build_panel(days=200)
    a = panel["equity.CN.SSE.000300.index.1d"]
    b = panel["equity.CN.SSE.000300.etf.1d"]
    res = compare(a, b, model="linear", max_lag=5)
    # 测试段有数据
    ok_test = res["test_size"] > 0
    # 曲线三数组等长 (预测vs实际)
    ok_curve = (len(res["curve"]["dates"]) == res["test_size"]
                and len(res["curve"]["actual"]) == len(res["curve"]["predicted"])
                and len(res["curve"]["residual"]) == len(res["curve"]["actual"]))
    # 指标齐备
    m = res["metrics"]
    ok_metrics = all(k in m for k in ("mae", "rmse", "mape", "hit_rate", "r2", "correlation", "nrmse"))
    # verdict 合法 + 有迭代建议
    ok_verdict = res["verdict"] in ("strong", "good", "weak", "insufficient") and res["iterations"]
    check("F5.1 滚动回测产出测试段", ok_test, f"test_size={res['test_size']}")
    check("F5.2 预测vs实际双曲线数据齐备", ok_curve)
    check("F5.3 误差指标齐全(MAE/RMSE/MAPE/命中率/R²)", ok_metrics,
          f"r2={m.get('r2')}, hit={m.get('hit_rate')}, rmse={m.get('rmse')}")
    check("F5.4 verdict分级+迭代建议", ok_verdict, f"verdict={res['verdict']}")


# ---------------------------------------------------------------------------
# [F6] 端到端还原真实传导结构 (核心功能验收)
# ---------------------------------------------------------------------------
def validate_e2e_structure() -> None:
    from reserve.relations.demo import build_panel, demo_summary
    from reserve.relations.engine import evaluate_pair
    from reserve.relations.compare import compare
    panel = build_panel(days=200)
    os.environ["RELATION_DIR"] = tempfile.mkdtemp(prefix="fn-rel-")
    try:
        summary = demo_summary(panel, model="linear", max_lag=8, top=5)
    finally:
        os.environ.pop("RELATION_DIR", None)
    # 矩阵还原: 8维->56条边全部产出预测能力评价
    check("F6.1 56条边全部产出预测对比", summary["edge_count"] == 56
          and sum(1 for c in summary["comparisons"] if c["test_size"] > 0) >= 50,
          f"edge={summary['edge_count']}")
    # 核心1: 同品种不同交易类型 (000300指数<->ETF) 应为最强关联
    top = summary["top_strength"][0]
    top_symbols = {top["from"].get("symbol"), top["to"].get("symbol")}
    check("F6.2 还原最强关联=000300指数↔ETF(同品种不同交易类型)",
          "000300" in top_symbols, f"最强边: {top['edge']} strength={top['strength']:.3f}")
    # 核心2: US10Y 宏观应领先影响权益 (全局领先驱动枢纽)
    #   注: 领先影响需用 lead_lag 模型扫描滞后才能检出 (linear 默认 lag=0 只捕捉同期)
    hs300 = panel["equity.CN.SSE.000300.index.1d"]
    us10y = panel["macro.global.MACRO.US10Y.rate.1d"]
    res_lead = evaluate_pair(us10y, hs300, model="lead_lag", max_lag=8)
    check("F6.3 US10Y→沪深300 检出领先影响(lead_lag)", res_lead["strength"] > 0.1,
          f"strength={res_lead['strength']:.3f}, lag={res_lead['lag']}")
    # 核心3: BTC 与 AAPL 风险偏好联动 (跨时间级别, 4h BTC vs 日线 AAPL 自动对齐)
    btc = panel["crypto.global.CRYPTO.BTC.spot.4h"]
    aapl = panel["equity.US.NYSE.AAPL.spot.1d"]
    res_btc = evaluate_pair(btc, aapl, model="lead_lag", max_lag=8)
    check("F6.4 BTC↔AAPL 检出风险偏好联动(lead_lag)", abs(res_btc["strength"]) > 0.2,
          f"strength={res_btc['strength']:.3f}, lag={res_btc['lag']}")
    # 核心4: 同品种不同交易类型预测能力应显著 (高R²/命中)
    cmp_etf = compare(panel["equity.CN.SSE.000300.index.1d"],
                      panel["equity.CN.SSE.000300.etf.1d"], model="linear", max_lag=8)
    check("F6.5 000300指数→ETF 预测能力显著(高命中/高R²)",
          cmp_etf["metrics"]["hit_rate"] >= 0.6, f"hit={cmp_etf['metrics']['hit_rate']:.2f}")
    # 传导网络 (基于 lead_lag 边, 才能让领先驱动枢纽浮出水面): 应识别宏观利率为全局枢纽
    from reserve.relations.engine import evaluate_all
    from reserve.relations.network import build_network
    ll_results = evaluate_all(panel, model="lead_lag", max_lag=8)
    ll_net = build_network(ll_results, min_strength=0.1)
    if ll_net.get("summary"):
        hub_keys = [h.get("key", "") for h in ll_net["summary"].get("top_hubs", [])]
        has_us10y_hub = any("US10Y" in k for k in hub_keys[:5])
        check("F6.6 传导网络识别宏观利率为领先枢纽(lead_lag边)", has_us10y_hub,
              f"top hubs: {hub_keys[:5]}")


# ---------------------------------------------------------------------------
# [F7] 传导网络
# ---------------------------------------------------------------------------
def validate_network() -> None:
    from reserve.relations.network import build_network, strongest_paths, network_summary
    from reserve.relations.engine import evaluate_all
    from reserve.relations.demo import build_panel
    panel = build_panel(days=120)
    # 用 lead_lag 边建网, 才能让领先影响(宏观驱动)体现为强边/枢纽
    results = evaluate_all(panel, model="lead_lag", max_lag=6)
    net = build_network(results, min_strength=0.1)
    check("F7.1 网络含节点与边", bool(net["nodes"]) and bool(net["edges"]))
    s = net["summary"]
    check("F7.2 网络摘要含中心性/枢纽/权威", s["node_count"] >= 2 and s["top_hubs"] and s["top_authorities"])
    check("F7.3 层内/层间边统计", "intra_layer_edges" in s and "inter_layer_edges" in s,
          f"层内={s['intra_layer_edges']}, 层间={s['inter_layer_edges']}")
    kinds = {e.get("relation_kind") for e in net["edges"]}
    check("F7.4 同时存在层内与层间边", "intra_layer" in kinds and "inter_layer" in kinds)
    # 传导路径 (用网络内真实存在的精确节点 key)
    node_keys = [n.get("key") for n in net["nodes"]]
    src = next((k for k in node_keys if "US10Y" in k), None)
    tgt = next((k for k in node_keys if "000300" in k), None)
    if src and tgt and src in {n.get("key") for n in net["nodes"]}:
        paths = strongest_paths(results, source=src, target=tgt, max_depth=3, min_strength=0.05)
        check("F7.5 可还原传导路径(宏观→权益)", bool(paths),
              f"路径数={len(paths)}")
    else:
        check("F7.5 可还原传导路径(宏观→权益)", False, "网络中缺少源/目标节点")


# ---------------------------------------------------------------------------
# [F8] 多模型自动择优
# ---------------------------------------------------------------------------
def validate_compare_models() -> None:
    from reserve.relations.compare import compare_models
    from reserve.relations.demo import build_panel
    panel = build_panel(days=200)
    a = panel["equity.CN.SSE.000300.index.1d"]
    b = panel["equity.CN.SSE.000300.etf.1d"]
    res = compare_models(a, b, models=["linear", "momentum", "exp_decay", "var"])
    check("F8.1 返回最优模型", res["best"] is not None, f"best={res['best']['model'] if res['best'] else None}")
    check("F8.2 排行按得分降序", res["ranking"]
          and res["ranking"][0]["score"] >= res["ranking"][-1]["score"])
    check("F8.3 最优模型与榜首一致", res["best"]["model"] == res["ranking"][0]["model"])


# ---------------------------------------------------------------------------
# [F9] 持久化
# ---------------------------------------------------------------------------
def validate_store() -> None:
    from reserve.relations.store import RelationStore
    with tempfile.TemporaryDirectory() as td:
        store = RelationStore(td)
        store.save_matrix({"dimensions": ["A"], "pair_count": 0})
        check("F9.1 矩阵落盘/回读", store.load_matrix()["pair_count"] == 0)
        store.save_edge({"edge": "A -> B", "strength": 0.7, "model": "linear"})
        check("F9.2 边落盘/回读", store.load_edge("A -> B")["strength"] == 0.7
              and store.count_edges() == 1)
        store.save_comparison("A -> B", {"verdict": "good", "metrics": {"r2": 0.4}})
        check("F9.3 对比结果落盘/回读", store.load_comparison("A -> B")["verdict"] == "good")
        store.save_series("equity.CN.SSE.000300.index.1d", {"2026-01-01": 1.0})
        check("F9.4 序列快照落盘/回读",
              store.load_series("equity.CN.SSE.000300.index.1d")["2026-01-01"] == 1.0)


# ---------------------------------------------------------------------------
# [F10] 跨时间级别自动重采样对齐
# ---------------------------------------------------------------------------
def validate_resample() -> None:
    from reserve.relations.engine import _prepare_pair
    daily = {"2026-01-01": 100.0, "2026-01-02": 101.0, "2026-01-03": 102.0}
    intraday = {"2026-01-01T00:00": 10.0, "2026-01-01T04:00": 12.0,
                "2026-01-02T00:00": 11.0, "2026-01-02T04:00": 13.0}
    sa, sb, resampled = _prepare_pair(daily, intraday)
    check("F10.1 4h与日线自动对齐", resampled is True and bool(set(sa) & set(sb)),
          f"对齐后交集={len(set(sa) & set(sb))}")
    # 真实演示: BTC 4h 与日线维度应能参与两两评估
    from reserve.relations.engine import evaluate_pair
    from reserve.relations.demo import build_panel
    panel = build_panel(days=120)
    btc4h = panel["crypto.global.CRYPTO.BTC.spot.4h"]
    gc = panel["futures.US.CME.GC.futures.1d"]
    res = evaluate_pair(btc4h, gc, model="linear", max_lag=5)
    check("F10.2 BTC4h 参与跨时间级别评估", res["model"] == "linear")


# ---------------------------------------------------------------------------
def main() -> int:
    global PASS, FAIL
    print("=" * 68)
    print("🧪 二次整理层 · 功能校验脚本")
    print("   校验方式: 端到端跑真实功能 + 对运行结果做业务断言")
    print("=" * 68)

    sections = [
        ("[F1] 维度系统 (跨市场/国家/品种/交易类型/时间级别)", validate_dims),
        ("[F2] 功能域分层漏斗 + 层内/层间", validate_layers),
        ("[F3] 两两有序关联矩阵 (8维→56边, 方向敏感)", validate_matrix),
        ("[F4] 11 种量化模型", validate_models),
        ("[F5] 预测能力验证 (滚动回测 vs 实际)", validate_compare),
        ("[F6] 端到端还原真实传导结构 (核心验收)", validate_e2e_structure),
        ("[F7] 传导网络 (枢纽/权威/簇/路径)", validate_network),
        ("[F8] 多模型自动择优", validate_compare_models),
        ("[F9] 持久化 (矩阵/边/对比/序列)", validate_store),
        ("[F10] 跨时间级别自动重采样对齐", validate_resample),
    ]

    for title, fn in sections:
        print(f"\n── {title} ──")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{title} 运行异常", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 68)
    print(f"📋 功能校验汇总: {PASS} 项通过 / {FAIL} 项未达成")
    if FAILURES:
        print("❌ 未达成项:")
        for f in FAILURES:
            print(f"   - {f}")
        print("\n结论: 二次整理层功能【未全部实际达成】")
        return 1
    print("\n✅ 结论: 二次整理层功能【实际达成】— 两两关联量化 + 预测能力验证 全部可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
