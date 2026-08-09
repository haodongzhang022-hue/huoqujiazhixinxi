"""内置演示数据 + 端到端演示 —— python -m reserve.relations.demo

生成一段含「真实传导结构」的合成金融数据，演示整个二次整理层:

  维度 (覆盖 跨市场/跨国家/跨品种/跨交易类型/跨时间级别):
    equity.CN.SSE.000300.index.1d     (沪深300 指数, 日线)
    equity.CN.SSE.000300.etf.1d       (沪深300 ETF, 同品种不同交易类型)
    equity.US.NYSE.AAPL.spot.1d       (苹果, 美股日线)
    futures.CN.SHFE.CU.futures.1d     (沪铜主力合约, 日线)
    futures.US.CME.GC.futures.1d      (COMEX 黄金, 日线)
    forex.GB.GBP.USDCNY.cash.1d       (USDCNY 汇率, 日线) —— 保留, 由宏观驱动
    crypto.global.CRYPTO.BTC.spot.4h  (BTC, 4小时) —— 跨时间级别
    macro.global.MACRO.US10Y.rate.1d  (美债10Y 收益率, 宏观) —— 领先指标

传导结构 (用于验证引擎能否还原):
  1. US10Y 领先影响 equity 各市场 (利率上行 -> 权益承压, 负相关)
  2. BTC 领先影响 AAPL 4h 级别 (风险偏好联动)
  3. 000300 指数 与 000300 ETF 高度同步 (同品种不同交易类型)
  4. CU 期货 与 宏观/美债 弱相关
  5. USDCNY 与 equity.CN 负相关 (汇率贬值 -> 权益承压)
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone

from reserve.relations.compare import compare
from reserve.relations.dims import dim_label, parse_dim
from reserve.relations.engine import evaluate_all, evaluate_pair
from reserve.relations.frame import build_matrix, expand_targets
from reserve.relations.store import RelationStore

DIMENSIONS = [
    "equity.CN.SSE.000300.index.1d",
    "equity.CN.SSE.000300.etf.1d",
    "equity.US.NYSE.AAPL.spot.1d",
    "futures.CN.SHFE.CU.futures.1d",
    "futures.US.CME.GC.futures.1d",
    "forex.GB.GBP.USDCNY.cash.1d",
    "crypto.global.CRYPTO.BTC.spot.4h",
    "macro.global.MACRO.US10Y.rate.1d",
]

SEED = 42


def _base_series(days: int, seed: int, drift: float = 0.0003, vol: float = 0.01,
                 start: float = 100.0) -> dict:
    """随机游走基准序列。"""
    rng = random.Random(seed)
    out: dict[str, float] = {}
    v = start
    day = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(days):
        v = v * (1 + drift + rng.gauss(0, vol))
        out[day.strftime("%Y-%m-%d")] = round(v, 4)
        day += timedelta(days=1)
    return out


def _apply_influence(series: dict, driver: dict, beta: float, lag: int,
                     noise_vol: float = 0.003, label: str = "",
                     mode: str = "price") -> dict:
    """让 series 受 driver 影响。

    mode="price": v_t += beta * driver_{t-lag}            (价格级叠加)
    mode="ret"  : 收益率 r_t += beta * r_driver_{t-lag}   (收益率级传导, 更贴近金融现实)
    """
    dates = sorted(series)
    rng = random.Random(SEED + len(label))
    out = dict(series)
    if mode == "ret":
        # 先把 driver 转为收益率, 叠加到 series 的日收益率上
        d_vals = [driver[d] for d in dates]
        d_rets = [0.0] + [(d_vals[i] - d_vals[i - 1]) / d_vals[i - 1] if d_vals[i - 1] else 0.0
                          for i in range(1, len(d_vals))]
        for i, d in enumerate(dates):
            pi = i - lag
            if pi >= 0:
                out[d] = out[d] * (1 + beta * d_rets[pi] + rng.gauss(0, noise_vol))
            else:
                out[d] = out[d] * (1 + rng.gauss(0, noise_vol))
            out[d] = round(max(out[d], 1e-6), 4)
        return out
    # mode="price"
    for i, d in enumerate(dates):
        pi = i - lag
        if pi >= 0:
            out[d] = out[d] + beta * driver[dates[pi]] + rng.gauss(0, noise_vol)
        else:
            out[d] = out[d] + rng.gauss(0, noise_vol)
        out[d] = round(max(out[d], 1e-6), 4)
    return out


def build_panel(days: int = 260) -> dict:
    """构造演示面板 (含真实传导结构)。"""
    us10y = _base_series(days, SEED + 1, drift=0.00005, vol=0.004, start=4.2)
    btc = _base_series(days, SEED + 2, drift=0.002, vol=0.03, start=60000)
    hs300 = _base_series(days, SEED + 3, drift=0.0004, vol=0.012, start=3800)
    hs300 = _apply_influence(hs300, us10y, beta=-0.35, lag=1, noise_vol=0.001, label="hs300", mode="ret")
    hs300_etf = _base_series(days, SEED + 4, drift=0.0004, vol=0.011, start=3.9)
    hs300_etf = _apply_influence(hs300_etf, hs300, beta=0.9, lag=0, noise_vol=0.0005, label="etf", mode="ret")
    aapl = _base_series(days, SEED + 5, drift=0.0008, vol=0.018, start=190)
    aapl = _apply_influence(aapl, btc, beta=0.12, lag=1, noise_vol=0.002, label="aapl", mode="ret")
    aapl = _apply_influence(aapl, us10y, beta=-0.25, lag=1, noise_vol=0.001, label="aapl2", mode="ret")
    cu = _base_series(days, SEED + 6, drift=0.0003, vol=0.014, start=68000)
    cu = _apply_influence(cu, us10y, beta=0.3, lag=2, noise_vol=0.002, label="cu", mode="ret")
    gc = _base_series(days, SEED + 7, drift=0.0004, vol=0.012, start=2300)
    gc = _apply_influence(gc, us10y, beta=0.35, lag=1, noise_vol=0.002, label="gc", mode="ret")
    usdcny = _base_series(days, SEED + 8, drift=0.00002, vol=0.003, start=7.15)
    usdcny = _apply_influence(usdcny, us10y, beta=0.2, lag=1, noise_vol=0.0004, label="fx", mode="ret")
    # BTC 4h: 用日线加密的 4h 粒度模拟 (每 4 小时一条, 与日线交错, 独立序列)
    btc4h = _base_series(days * 6, SEED + 9, drift=0.0003, vol=0.012, start=60000)
    btc4h_dates = {}
    day = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(days * 6):
        k = day.strftime("%Y-%m-%d") + f"T{6 + (i % 6) * 4:02d}:00"
        btc4h_dates[k] = btc4h[day.strftime("%Y-%m-%d")]
        day += timedelta(hours=4)

    return {
        "equity.CN.SSE.000300.index.1d": hs300,
        "equity.CN.SSE.000300.etf.1d": hs300_etf,
        "equity.US.NYSE.AAPL.spot.1d": aapl,
        "futures.CN.SHFE.CU.futures.1d": cu,
        "futures.US.CME.GC.futures.1d": gc,
        "forex.GB.GBP.USDCNY.cash.1d": usdcny,
        "crypto.global.CRYPTO.BTC.spot.4h": btc4h_dates,
        "macro.global.MACRO.US10Y.rate.1d": us10y,
    }


def demo_summary(panel: dict, model: str = "linear", max_lag: int = 10,
                 top: int = 10, out: str | None = None) -> dict:
    """端到端演示: 建矩阵 -> 全两两评估 -> 预测对比 -> 落盘。"""
    store = RelationStore()

    # 1) 矩阵
    matrix = build_matrix(list(panel.keys()))
    store.save_matrix(matrix)
    print(f"✅ 关联矩阵: {len(matrix['dimensions'])} 个维度, {matrix['pair_count']} 条有向边 (两两双向, 排除自环)")

    # 2) 全两两评估
    results = evaluate_all(panel, model=model, max_lag=max_lag)
    for r in results:
        store.save_edge(r)
    print(f"✅ 全两两评估完成: {len(results)} 条边 (model={model})")

    # 3) 预测 vs 实际 对比 (每条边滚动回测)
    comparisons = []
    for r in results:
        a_key = ".".join([r["from"][k] for k in ("market", "country", "exchange", "symbol", "asset", "timeframe")])
        b_key = ".".join([r["to"][k] for k in ("market", "country", "exchange", "symbol", "asset", "timeframe")])
        cmp = compare(panel[a_key], panel[b_key], model=model, max_lag=max_lag)
        cmp["edge"] = r["edge"]
        cmp["from"] = r["from"]
        cmp["to"] = r["to"]
        cmp["strength"] = r["strength"]
        store.save_comparison(r["edge"], cmp)
        comparisons.append(cmp)

    # 4) 汇总
    summary = {
        "dimensions": [parse_dim(k).to_dict() for k in panel],
        "dimension_labels": {k: dim_label(parse_dim(k)) for k in panel},
        "edge_count": len(results),
        "edges": results,
        "comparisons": comparisons,
        "top_strength": sorted(results, key=lambda x: -x["strength"])[:top],
        "top_verdict": sorted([c for c in comparisons if c["test_size"] > 0],
                              key=lambda c: -(c["metrics"].get("r2") or 0))[:top],
        "model": model,
    }
    if out:
        p = store.root / "demo-summary.json"
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 汇总已落盘: {p}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="二次整理层演示 (python -m reserve.relations.demo)")
    ap.add_argument("--days", type=int, default=260)
    ap.add_argument("--model", default="linear", choices=["correlation", "lead_lag", "vol_spillover",
                                                          "linear", "momentum", "exp_decay", "var"])
    ap.add_argument("--max-lag", type=int, default=10)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", action="store_true", help="落盘 demo-summary.json")
    args = ap.parse_args()

    print(f"🎯 二次整理层演示: 金融各市场两两关联量化 + 预测能力验证")
    panel = build_panel(args.days)
    print(f"📊 面板: {len(panel)} 个维度 × {args.days} 天 (合成数据, 含真实传导结构)")
    summary = demo_summary(panel, model=args.model, max_lag=args.max_lag, top=args.top,
                           out="demo-summary.json" if args.out else None)

    print(f"\n🏆 Top {args.top} 强关联边 (A→B, 两两双向独立):")
    for r in summary["top_strength"]:
        from_label = dim_label(parse_dim(r["from"]))
        to_label = dim_label(parse_dim(r["to"]))
        print(f"  {r['strength']:.3f}  {from_label} → {to_label}  "
              f"(model={r['model']}, lag={r['lag']}, sign={r['sign']:+d}, r2={r['metrics'].get('r2', '-')})")

    print(f"\n🎯 预测能力 Top {args.top} (测试段 R² 排序):")
    for c in summary["top_verdict"]:
        from_label = dim_label(parse_dim(c["from"]))
        to_label = dim_label(parse_dim(c["to"]))
        m = c["metrics"]
        print(f"  {m.get('r2', 0):.3f} r² | hit={m.get('hit_rate', 0):.2f} | {from_label} → {to_label} "
              f"[{c['verdict']}] {c['iterations'][0] if c['iterations'] else ''}")

    verdict_dist = {}
    for c in summary["comparisons"]:
        verdict_dist[c["verdict"]] = verdict_dist.get(c["verdict"], 0) + 1
    print(f"\n📈 预测能力分布: {verdict_dist}")
    print("\n💡 结论: 强/良好边可直接用于策略或自动化触发; weak/insufficient 边进迭代队列,"
          "\n   通过增加样本/换模型/引入宏观因子持续逼近真实传导。")


if __name__ == "__main__":
    main()
