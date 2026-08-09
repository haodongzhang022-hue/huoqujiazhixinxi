"""预测 vs 实际 对比 —— 验证模型「预测能力到底够不够」。

ISSUE #7 核心验收标准: 把「模型预测出来的互相影响」和「实际的影响曲线」放一起对比，
量化误差，才能知道预测能力够不够、后续该怎么迭代。

本模块提供两种对比能力:

  1. `predict_impact`   —— 用拟合好的模型参数，预测 A 对 B 的“影响贡献曲线”
                           (即模型认为 A 的变化会在 B 上引起多大的响应)
  2. `compare`          —— 滚动回测: 训练段拟合 -> 测试段预测 vs 实际，逐点对比
                           + 误差统计 (MAE / RMSE / MAPE / 方向命中率 / R²)

曲线数据结构:
  {
    "edge": "A -> B",
    "dates": [...],
    "actual":  [...],     # B 的实际值/收益率
    "predicted": [...],   # 模型预测的 B (或影响贡献)
    "residual": [...],    # actual - predicted
  }
"""

from __future__ import annotations

import math

from reserve.relations.engine import (_lagged, _linear_fit, _pearson, _tanh_norm,
                                      aligned_dates, align_series, exp_decay_fit,
                                      returns, _prepare_pair)


def _mae(xs: list[float], ys: list[float]) -> float:
    if not xs:
        return 0.0
    return sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs)


def _rmse(xs: list[float], ys: list[float]) -> float:
    if not xs:
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(xs, ys)) / len(xs))


def _mape(actual: list[float], predicted: list[float]) -> float | None:
    vals = []
    for a, p in zip(actual, predicted):
        if a != 0:
            vals.append(abs((a - p) / a))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _hit_rate(actual: list[float], predicted: list[float]) -> float:
    """方向命中率: 预测与实际的变动方向是否一致。"""
    if len(actual) < 2:
        return 0.0
    hits = 0
    total = 0
    for i in range(1, len(actual)):
        da = actual[i] - actual[i - 1]
        dp = predicted[i] - predicted[i - 1]
        if da == 0 and dp == 0:
            hits += 1
            total += 1
        elif da * dp > 0:
            hits += 1
            total += 1
        elif da != 0:
            total += 1
    return hits / total if total else 0.0


def predict_impact(series_a: dict, series_b: dict, params: dict, lag: int = 1,
                   model: str = "linear") -> dict:
    """用模型参数预测「A 对 B 的影响贡献曲线」(基于收益率, 与拟合一致)。

    - linear / exp_decay: predicted_rB[t] = a + b * rA[t-lag]
    - momentum / var     : predicted_rB[t] = a + b * rA[t-lag] + c * rB[t-1]
    返回 {dates, actual, predicted, residual} (actual = B 的实际收益率)。
    """
    ra = returns(series_a)
    rb = returns(series_b)
    dates = sorted(set(ra) & set(rb))
    a_, b_ = params.get("a", 0.0), params.get("b", 0.0)
    c_ = params.get("c", 0.0)
    actual, predicted = [], []
    for i, d in enumerate(dates):
        actual.append(float(rb[d]))
        pi = i - lag
        # 滞后可能为负 (B 领先 A): 用未来值配对, 保证索引合法
        if pi < 0:
            pi = i + abs(lag)
        if 0 <= pi < len(dates) and dates[pi] in ra:
            base = a_ + b_ * float(ra[dates[pi]])
            if c_ and i - 1 >= 0:
                base += c_ * float(rb[dates[i - 1]])
            predicted.append(base)
        else:
            predicted.append(float(rb[d]))  # 无前置数据 -> 用实际值占位
    residual = [actual[i] - predicted[i] for i in range(len(actual))]
    return {"dates": dates, "actual": actual, "predicted": predicted, "residual": residual}


def compare(series_a: dict, series_b: dict, model: str = "linear",
            lag: int | None = None, train_ratio: float = 0.7,
            max_lag: int = 10) -> dict:
    """滚动回测对比: 训练段拟合 -> 测试段预测 vs 实际。

    返回:
      {
        "edge": 由调用方补充,
        "model": model,
        "train_dates": [...], "test_dates": [...],
        "train_size": n, "test_size": m,
        "curve": {"dates": [...], "actual": [...], "predicted": [...], "residual": [...]},
        "metrics": {mae, rmse, mape, hit_rate, r2, correlation},
        "verdict": "strong | good | weak | insufficient",   # 预测能力评价
        "iterations": ["提示后续迭代方向", ...],
      }

    verdict 规则 (供快速判断预测能力够不够):
      strong: 测试段 R² >= 0.5 且 方向命中率 >= 0.65
      good  : R² >= 0.3 或 命中率 >= 0.6
      weak  : 有信号但弱 (R² < 0.3 且 命中率 < 0.6)
      insufficient: 数据不足或几乎无信号
    """
    from reserve.relations.engine import evaluate_pair

    # 0) 对齐预处理 (含跨时间级别自动重采样)
    series_a, series_b, _ = _prepare_pair(series_a, series_b)

    # 1) 训练段拟合
    aligned = aligned_dates(series_a, series_b)
    n = len(aligned)
    if n < 8:
        return {"model": model, "train_size": n, "test_size": 0,
                "curve": {"dates": [], "actual": [], "predicted": [], "residual": []},
                "metrics": {}, "verdict": "insufficient", "iterations": ["数据不足, 需补充更多历史样本"]}

    split = max(3, int(n * train_ratio))
    train_dates = [d for d, _, _ in aligned[:split]]
    test_dates = [d for d, _, _ in aligned[split:]]
    sa_train = {d: v for d, v, _ in aligned[:split]}
    sb_train = {d: v for d, _, v in aligned[:split]}

    fit = evaluate_pair(sa_train, sb_train, model=model, max_lag=max_lag, lag=lag)
    use_lag = fit.get("lag", 0)
    params = fit.get("params", {})
    if not params or fit.get("insufficient_data"):
        return {"model": model, "train_size": len(train_dates), "test_size": len(test_dates),
                "curve": {"dates": [], "actual": [], "predicted": [], "residual": []},
                "metrics": {}, "verdict": "insufficient",
                "iterations": ["训练段数据不足以拟合模型, 请补充历史数据或降低模型复杂度"]}

    # 2) 测试段预测 vs 实际 (用训练段参数, 全序列滚动预测)
    curve = predict_impact(series_a, series_b, params, lag=use_lag, model=model)
    test_set = set(test_dates)
    test_idx = [i for i, d in enumerate(curve["dates"]) if d in test_set]
    actual = [curve["actual"][i] for i in test_idx]
    predicted = [curve["predicted"][i] for i in test_idx]
    residual = [curve["residual"][i] for i in test_idx]
    test_curve = {"dates": [curve["dates"][i] for i in test_idx],
                  "actual": actual, "predicted": predicted, "residual": residual}

    # 3) 指标
    metrics = {
        "mae": round(_mae(actual, predicted), 6),
        "rmse": round(_rmse(actual, predicted), 6),
        "mape": round(_mape(actual, predicted), 6) if _mape(actual, predicted) is not None else None,
        "hit_rate": round(_hit_rate(actual, predicted), 4),
        "r2": round(_linear_fit(actual, predicted)[2], 4),
        "correlation": round(_pearson(actual, predicted), 4),
    }
    if len(actual) == len(predicted) and len(actual) > 0:
        m = max(abs(v) for v in actual) if actual else 1.0
        metrics["nrmse"] = round(metrics["rmse"] / m if m else 0.0, 4)

    # 4) 评价与迭代建议
    r2 = metrics["r2"]
    hit = metrics["hit_rate"]
    if r2 >= 0.5 and hit >= 0.65:
        verdict, iters = "strong", [
            "预测能力较强, 可将该边纳入策略层/自动化触发",
            "建议继续增加样本并尝试更高阶模型 (VAR 多阶 / 神经网络) 以逼近上限",
        ]
    elif r2 >= 0.3 or hit >= 0.6:
        verdict, iters = "good", [
            "预测有可用信号, 可进入观察名单",
            "建议细分时间级别 / 增加领先指标, 或改用 exp_decay 加权近期数据",
        ]
    elif r2 > 0.05 or hit > 0.52:
        verdict, iters = "weak", [
            "信号偏弱, 不建议直接用于决策",
            "建议: 增加样本量 / 缩短预测窗口 / 引入更多解释变量 (宏观因子、波动率)",
        ]
    else:
        verdict, iters = "insufficient", [
            "几乎无预测能力 (随机水平), 该边暂不建模",
            "建议: 检查数据质量 / 该边可能确实不存在稳定传导, 标记为低置信边",
        ]

    return {"model": model, "train_dates": train_dates, "test_dates": test_dates,
            "train_size": len(train_dates), "test_size": len(test_dates),
            "curve": test_curve, "metrics": metrics, "verdict": verdict,
            "iterations": iters, "fit": fit}


def compare_models(series_a: dict, series_b: dict,
                   models: list[str] | None = None,
                   lag: int | None = None, train_ratio: float = 0.7,
                   max_lag: int = 10) -> dict:
    """多模型对比 —— 自动尝试多种模型, 挑出预测能力最优者 (响应 ISSUE 迭代建议「换模型」)。

    对每种模型跑 `compare`, 按测试段综合得分排序:
      score = r2*0.5 + hit_rate*0.3 + (1 - nrmse)*0.2
    返回 {best, ranking, comparisons}。
    """
    from reserve.relations.engine import MODELS

    if models is None:
        # 默认对比的模型集 (排除纯变量/事件类, 保留可预测的回归族 + VAR)
        models = [m for m in ("linear", "momentum", "exp_decay", "var", "correlation") if m in MODELS]
    comparisons = []
    for m in models:
        try:
            cmp = compare(series_a, series_b, model=m, lag=lag,
                          train_ratio=train_ratio, max_lag=max_lag)
        except Exception:
            continue
        cmp["model"] = m
        comparisons.append(cmp)

    def _score(c):
        mt = c.get("metrics") or {}
        r2 = mt.get("r2") or 0.0
        hit = mt.get("hit_rate") or 0.0
        nrmse = mt.get("nrmse")
        nr = 1.0 - nrmse if nrmse is not None else 0.5
        return round(r2 * 0.5 + hit * 0.3 + nr * 0.2, 4)

    for c in comparisons:
        c["_score"] = _score(c)
    comparisons.sort(key=lambda c: -c["_score"])
    ranking = [{"model": c["model"], "score": c.pop("_score", 0.0),
                "verdict": c.get("verdict"), "r2": (c.get("metrics") or {}).get("r2"),
                "hit_rate": (c.get("metrics") or {}).get("hit_rate")} for c in comparisons]
    best = comparisons[0] if comparisons else None
    if best:
        best.pop("_score", None)
    return {"best": best, "ranking": ranking, "comparisons": comparisons}
