"""关联评估引擎 —— 两两双向影响的计算与量化。

输入: 时间序列面板 (每个维度一条 {date: value} 序列，未对齐会自动按时间轴对齐)
输出: 每条有向边 (A→B) 的评估结果:

  {
    "edge": "A -> B",
    "direction": "A -> B",
    "model": "correlation | lead_lag | vol_spillover | linear | momentum | exp_decay | var | rolling_corr | regime_shift | event_study | self_corr",
    "params": {...},                      # 模型参数 (拟合结果)
    "strength": 0.73,                     # 归一化影响强度 0~1 (方向: A 对 B 的影响)
    "sign": +1 | -1,                      # 正/负相关方向
    "lag": 1,                             # 领先滞后天数 (A 领先 B 的期数)
    "stability": 0.81,                    # 稳定性 0~1 (滚动窗口方差小 -> 稳定)
    "sample_size": 120,
    "metrics": {"pearson": ..., "r2": ...},
    "modeled_at": "...",
  }

模型说明 (从简到繁, 满足「固定值 / 变量 / 模型拟合 / 更复杂」的渐进需求):
  correlation    : Pearson 相关系数 (固定值型关联)
  lead_lag       : 扫描滞后 ±max_lag 找最大 |corr| -> 领先滞后关系
  vol_spillover  : 波动溢出 (收益绝对值的相关) —— 风险传导
  linear         : 线性回归 B_t = a + b*A_(t-lag) -> 量化弹性系数 b
  momentum       : 动量扩散 B_t = a + b*A_(t-lag) + c*B_(t-1) (自回归+扩散)
  exp_decay      : 指数衰减加权影响 (近期影响大, 远期衰减)
  var            : 双变量向量自回归 (VAR(1)) -> 脉冲响应/格兰杰因果
  rolling_corr   : 滚动相关 —— 关联强度随时间的"变量"曲线 (回答"大多数时候可能是变量")
  regime_shift   : 结构突变/区间检测 —— 关联关系是否随时间发生切换 (强化/反转/消失)
  event_study    : 事件研究 —— A 发生异常波动后, B 在事件窗口内的反应 (事件驱动传导)
  self_corr      : 自相关 —— 序列自身的动量/均值回归特性 (自身影响, 用于识别"自己影响自己")

所有模型都是**方向敏感**的: 计算 A→B 与 B→A 时 A/B 互换、滞后方向互换。
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

MODELS = ["correlation", "lead_lag", "vol_spillover", "linear", "momentum", "exp_decay", "var",
          "rolling_corr", "regime_shift", "event_study", "self_corr"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def align_series(series_a: dict, series_b: dict, max_lag: int = 10) -> list[tuple[float, float]]:
    """按日期对齐两条序列 (取交集, 按时间排序), 返回 [(a, b), ...]。"""
    common = sorted(set(series_a) & set(series_b))
    return [(float(series_a[d]), float(series_b[d])) for d in common]


def aligned_dates(series_a: dict, series_b: dict) -> list[tuple[str, float, float]]:
    """按日期对齐, 返回 [(date, a, b), ...] (供预测对比用)。"""
    common = sorted(set(series_a) & set(series_b))
    return [(d, float(series_a[d]), float(series_b[d])) for d in common]


def resample_daily(series: dict) -> dict:
    """把日内序列 (key 含 'T' 或 ISO 时间) 按日聚合为日均值, 实现跨时间级别对齐。

    例如 4h 序列 "2025-01-01T06:00" -> 归入 "2025-01-01" 取当日均值。
    """
    out: dict[str, list[float]] = {}
    for k, v in series.items():
        day = str(k)[:10]
        out.setdefault(day, []).append(float(v))
    return {d: sum(vals) / len(vals) for d, vals in out.items()}


def _prepare_pair(series_a: dict, series_b: dict):
    """对齐前预处理: 若两序列无共同日期且一方为日内序列, 自动重采样为日线。

    返回 (sa, sb, resampled_flag)。
    """
    sa, sb = series_a, series_b
    resampled = False
    if not (set(sa) & set(sb)):
        has_intraday_a = any("T" in str(k) for k in sa)
        has_intraday_b = any("T" in str(k) for k in sb)
        if has_intraday_a:
            sa = resample_daily(sa)
            resampled = True
        if has_intraday_b:
            sb = resample_daily(sb)
            resampled = True
    return sa, sb, resampled


def returns(series: dict) -> dict:
    """收益率序列 (变化率, 更平稳): r_t = (v_t - v_{t-1}) / v_{t-1}。"""
    out: dict[str, float] = {}
    prev = None
    for d in sorted(series):
        v = float(series[d])
        if prev is not None and prev != 0:
            out[d] = (v - prev) / abs(prev)
        prev = v
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _linear_fit(xs: list[float], ys: list[float]):
    """最小二乘 y = a + b*x -> (a, b, r2)。"""
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return my, 0.0, 0.0
    b = sxy / sxx
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, max(0.0, min(1.0, r2))


def _lagged(series_a: dict, series_b: dict, lag: int) -> list[tuple[float, float]]:
    """A 领先 lag 期 -> B: 配对 (A[t-lag], B[t])。"""
    dates = sorted(set(series_a) & set(series_b))
    pairs = []
    for d in dates:
        prev_d = None
        idx = dates.index(d)
        pi = idx - lag
        if pi >= 0:
            prev_d = dates[pi]
        if prev_d is not None and prev_d in series_a and d in series_b:
            pairs.append((float(series_a[prev_d]), float(series_b[d])))
    return pairs


def lead_lag(series_a: dict, series_b: dict, max_lag: int = 10) -> dict:
    """扫描滞后 ±max_lag, 找 |corr| 最大的滞后 -> 领先滞后关系。

    正 lag = A 领先 B (A 过去值预测 B 当前值最强)。
    返回 {lag, corr, strength, sign}。
    """
    best = {"lag": 0, "corr": 0.0}
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            pairs = _lagged(series_a, series_b, lag)
        else:
            pairs = _lagged(series_b, series_a, -lag)
        if len(pairs) < 5:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        c = _pearson(xs, ys)
        if abs(c) > abs(best["corr"]):
            best = {"lag": lag, "corr": c}
    corr = best["corr"]
    # 负 lag 表示 B 领先 A: 样本量从 _lagged(B, A, |lag|) 取得 (避免把负 lag 传入 _lagged 导致越界)
    sample = _lagged(series_a, series_b, best["lag"]) if best["lag"] >= 0 \
        else _lagged(series_b, series_a, -best["lag"])
    return {
        "model": "lead_lag",
        "lag": best["lag"],
        "corr": corr,
        "sign": 1 if corr >= 0 else -1,
        "strength": abs(corr),
        "sample_size": max(3, len(sample)),
    }


def _stability(series_a: dict, series_b: dict, lag: int = 1, window: int = 10) -> float:
    """滚动窗口相关系数的稳定性 (1 - 变异系数, 越高越稳定)。

    负 lag 表示 B 领先 A, 与 _lagged 约定一致: 交换 A/B 并用 |lag| 计算。
    """
    if lag < 0:
        series_a, series_b, lag = series_b, series_a, -lag
    dates = sorted(set(series_a) & set(series_b))
    if len(dates) < window + 2:
        return 0.0
    corrs = []
    for i in range(len(dates) - window):
        sub_a = {d: series_a[d] for d in dates[i:i + window]}
        sub_b = {d: series_b[d] for d in dates[i:i + window]}
        pairs = _lagged(sub_a, sub_b, lag)
        if len(pairs) >= 5:
            corrs.append(_pearson([p[0] for p in pairs], [p[1] for p in pairs]))
    if len(corrs) < 2:
        return 0.0
    mu = statistics.fmean(corrs)
    if mu == 0:
        return 0.0
    sd = statistics.pstdev(corrs)
    cv = sd / abs(mu)
    return max(0.0, min(1.0, 1.0 - cv))


def _rolling_weights(n: int, half_life: float = 10.0) -> list[float]:
    """指数衰减权重: 最近样本权重最高, 越远越小。"""
    return [math.exp(-(n - 1 - i) / max(half_life, 1e-6)) for i in range(n)]


def exp_decay_fit(xs: list[float], ys: list[float], half_life: float = 10.0) -> dict:
    """指数衰减加权回归 (近因效应): 用权重最小二乘 y = a + b*x。"""
    n = len(xs)
    if n < 3:
        return {"a": 0.0, "b": 0.0, "r2": 0.0, "strength": 0.0}
    w = _rolling_weights(n, half_life)
    sw = sum(w)
    wx, wy = sum(w[i] * xs[i] for i in range(n)) / sw, sum(w[i] * ys[i] for i in range(n)) / sw
    sxx = sum(w[i] * (xs[i] - wx) ** 2 for i in range(n))
    sxy = sum(w[i] * (xs[i] - wx) * (ys[i] - wy) for i in range(n))
    if sxx == 0:
        return {"a": wy, "b": 0.0, "r2": 0.0, "strength": 0.0}
    b = sxy / sxx
    a = wy - b * wx
    ss_res = sum(w[i] * (ys[i] - (a + b * xs[i])) ** 2 for i in range(n))
    ss_tot = sum(w[i] * (ys[i] - wy) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"a": a, "b": b, "r2": max(0.0, min(1.0, r2)),
            "strength": min(1.0, abs(b) * math.sqrt(sxx / max(ss_tot, 1e-9)) + 0.0)}


def _tanh_norm(x: float, scale: float = 1.0) -> float:
    """把无界值映射到 0~1 的强度 (双曲正切归一化)。"""
    return abs(math.tanh(x / scale))


def rolling_corr(series_a: dict, series_b: dict, window: int = 20, max_lag: int = 5) -> dict:
    """滚动相关 —— 关联强度随时间的「变量」曲线 (回答 ISSUE 原文: 大多数时候可能是变量)。

    在滑动窗口内计算 Pearson 相关 (带领先滞后优化), 输出:
      curve: [{date, corr, strength}...]   # 逐窗口的时变关联
      mean / std / min / max / trend      # 汇总: 变量有多大、趋势如何
      strength: 取 |平均相关| (兼顾整体强度) 并与变量稳定性结合
      sign / lag / stability
    """
    dates = sorted(set(series_a) & set(series_b))
    n = len(dates)
    if n < window + 5:
        return {"curve": [], "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                "trend": 0.0, "strength": 0.0, "sign": 0, "lag": 0, "stability": 0.0,
                "window": window, "sample_size": n}
    ra = returns(series_a)
    rb = returns(series_b)
    curve = []
    for i in range(n - window + 1):
        win_a = {d: ra[d] for d in dates[i:i + window] if d in ra}
        win_b = {d: rb[d] for d in dates[i:i + window] if d in rb}
        best = 0.0
        best_lag = 0
        for lag in range(-max_lag, max_lag + 1):
            pairs = _lagged(win_a, win_b, lag) if lag >= 0 else _lagged(win_b, win_a, -lag)
            if len(pairs) < 5:
                continue
            c = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            if abs(c) > abs(best):
                best, best_lag = c, lag
        curve.append({"date": dates[i + window - 1], "corr": round(best, 4),
                      "strength": round(abs(best), 4), "lag": best_lag})
    corrs = [c["corr"] for c in curve]
    mean = sum(corrs) / len(corrs)
    sd = statistics.pstdev(corrs) if len(corrs) > 1 else 0.0
    trend = 0.0
    if len(corrs) >= 5:
        xs = list(range(len(corrs)))
        _, b, _ = _linear_fit(xs, corrs)
        trend = round(b, 5)
    mean_strength = abs(mean)
    # 变量强度: 均相关强度 + 趋势加分; 但高波动 (std 大) 说明关系不稳定, 折减
    stability = max(0.0, min(1.0, 1.0 - sd / max(abs(mean), 0.05) * 0.5))
    strength = min(1.0, mean_strength + abs(trend) * 2.0)
    return {"curve": curve, "mean": round(mean, 4), "std": round(sd, 4),
            "min": round(min(corrs), 4), "max": round(max(corrs), 4),
            "trend": trend, "strength": min(1.0, strength), "sign": 1 if mean >= 0 else -1,
            "lag": curve[-1]["lag"] if curve else 0, "stability": round(stability, 4),
            "window": window, "sample_size": n}


def regime_shift(series_a: dict, series_b: dict, window: int = 20, min_regime: int = 3) -> dict:
    """结构突变 / 区间检测 —— 关联关系是否随时间切换 (强化 / 反转 / 消失)。

    把全样本切成前后两段 (支持多段: 递归二分), 对比两段的相关系数:
      - 同向且增强   -> "strengthen" (关系强化)
      - 同向但减弱   -> "weaken"    (关系弱化)
      - 符号反转     -> "reverse"   (关系反转)
      - 一段无信号   -> "appear" / "disappear" (关系出现 / 消失)
    输出 break_date(突变点) / shift_type / delta / strength 等。
    """
    dates = sorted(set(series_a) & set(series_b))
    n = len(dates)
    if n < window * 2 + 4:
        return {"break_date": None, "shift_type": "none", "delta": 0.0, "pre_corr": 0.0,
                "post_corr": 0.0, "strength": 0.0, "sign": 0, "lag": 0,
                "stability": 0.0, "sample_size": n}
    ra = returns(series_a)
    rb = returns(series_b)

    def _seg_corr(seg_dates):
        pairs = [(ra[d], rb[d]) for d in seg_dates if d in ra and d in rb]
        if len(pairs) < 5:
            return 0.0, 0
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        c = _pearson(xs, ys)
        # 段内领先滞后 (符号一致时用绝对值最大)
        best = c
        best_lag = 0
        for lag in range(-max(1, window // 4), max(1, window // 4) + 1):
            p2 = _lagged(ra, rb, lag) if lag >= 0 else _lagged(rb, ra, -lag)
            p2 = [(x, y) for x, y in p2 if True]
            if len(p2) >= 5:
                c2 = _pearson([x for x, _ in p2], [y for _, y in p2])
                if abs(c2) > abs(best):
                    best, best_lag = c2, lag
        return best, best_lag

    best_split = None
    best_delta = -1.0
    for split in range(window, n - window + 1):
        pre = dates[:split]
        post = dates[split:]
        if len(pre) < 5 or len(post) < 5:
            continue
        c_pre, _ = _seg_corr(pre)
        c_post, _ = _seg_corr(post)
        delta = abs(c_post - c_pre)
        if delta > best_delta:
            best_delta = delta
            best_split = (split, c_pre, c_post)
    if best_split is None:
        return {"break_date": None, "shift_type": "none", "delta": 0.0, "pre_corr": 0.0,
                "post_corr": 0.0, "strength": 0.0, "sign": 0, "lag": 0,
                "stability": 0.0, "sample_size": n}
    split, c_pre, c_post = best_split
    break_date = dates[split]
    delta = c_post - c_pre
    same_sign = (c_pre >= 0) == (c_post >= 0)
    if abs(c_pre) < 0.05 and abs(c_post) < 0.05:
        shift_type = "none"
    elif abs(c_pre) < 0.05 and abs(c_post) >= 0.05:
        shift_type = "appear"
    elif abs(c_pre) >= 0.05 and abs(c_post) < 0.05:
        shift_type = "disappear"
    elif same_sign and abs(c_post) > abs(c_pre) * 1.3:
        shift_type = "strengthen"
    elif same_sign:
        shift_type = "weaken"
    else:
        shift_type = "reverse"
    sign = 1 if c_post >= 0 else -1
    strength = min(1.0, abs(c_post) + abs(delta) * 0.6)
    stability = max(0.0, min(1.0, 1.0 - abs(delta) / max(max(abs(c_pre), abs(c_post), 0.05), 1e-9) * 0.5))
    return {"break_date": break_date, "shift_type": shift_type, "delta": round(delta, 4),
            "pre_corr": round(c_pre, 4), "post_corr": round(c_post, 4),
            "strength": min(1.0, strength), "sign": sign, "lag": 0,
            "stability": round(stability, 4), "sample_size": n}


def event_study(series_a: dict, series_b: dict, window: int = 5, threshold: float = 2.0) -> dict:
    """事件研究 —— A 发生异常波动后, B 在事件窗口内的反应 (事件驱动传导)。

    1) 找 A 的异常事件日: |A 收益率| > threshold × 滚动标准差 (可选方向过滤)
    2) 统计事件后 B 的平均异常反应 (相对 B 自身滚动均值的 z-score)
    3) 输出: 事件数 / 平均反应 / 命中率 (B 同向反应比例) / 事件窗口曲线
    """
    dates = sorted(set(series_a) & set(series_b))
    n = len(dates)
    if n < 30:
        return {"events": [], "event_count": 0, "avg_response": 0.0, "hit_rate": 0.0,
                "strength": 0.0, "sign": 0, "lag": 0, "stability": 0.0, "sample_size": n}
    ra = returns(series_a)
    rb = returns(series_b)
    a_vals = [ra[d] for d in dates if d in ra]
    mu_a = statistics.fmean(a_vals)
    sd_a = statistics.pstdev(a_vals) if len(a_vals) > 1 else 1e-9
    # B 滚动均值/标准差 (用于标准化事件后反应)
    b_vals = [rb[d] for d in dates if d in rb]
    mu_b = statistics.fmean(b_vals)
    sd_b = statistics.pstdev(b_vals) if len(b_vals) > 1 else 1e-9
    events = []
    for i, d in enumerate(dates):
        if d not in ra or d not in rb:
            continue
        z_a = abs(ra[d] - mu_a) / max(sd_a, 1e-9)
        if z_a < threshold:
            continue
        # 事件窗口: 事件后 1..window 天 B 的累积反应
        resp = []
        for w in range(1, window + 1):
            j = i + w
            if j < len(dates) and dates[j] in rb:
                resp.append((rb[dates[j]] - mu_b) / max(sd_b, 1e-9))
        if not resp:
            continue
        cum = sum(resp) / len(resp)
        events.append({"date": d, "z_a": round(z_a, 3), "cum_response": round(cum, 4),
                       "direction": "up" if ra[d] >= mu_a else "down"})
    if len(events) < 2:
        return {"events": events, "event_count": len(events), "avg_response": 0.0,
                "hit_rate": 0.0, "strength": 0.0, "sign": 0, "lag": 1,
                "stability": 0.0, "sample_size": n}
    avg = statistics.fmean([e["cum_response"] for e in events])
    # 命中率: 同符号 (A 向上 -> B 也向上) 的比例
    hits = 0
    tot = 0
    for e in events:
        if e["direction"] == "up" and e["cum_response"] > 0:
            hits += 1
            tot += 1
        elif e["direction"] == "down" and e["cum_response"] < 0:
            hits += 1
            tot += 1
        elif e["cum_response"] != 0:
            tot += 1
    hit_rate = hits / tot if tot else 0.0
    strength = min(1.0, abs(avg) * 0.8 + hit_rate * 0.4)
    return {"events": events, "event_count": len(events), "avg_response": round(avg, 4),
            "hit_rate": round(hit_rate, 4), "strength": min(1.0, strength),
            "sign": 1 if avg >= 0 else -1, "lag": 1,
            "stability": round(min(1.0, hit_rate / 0.7), 4), "sample_size": n}


def self_corr(series: dict, max_lag: int = 10) -> dict:
    """自相关 —— 序列自身的动量/均值回归特性 (识别"自己影响自己")。

    输出各滞后期的自相关系数, 以及最强自相关滞后:
      lag1_ac / half_life_est(自相关半衰期) / mean_reverting(是否均值回归: lag1<0)
    """
    dates = sorted(series)
    n = len(dates)
    if n < 10:
        return {"lag1_ac": 0.0, "best_lag": 0, "best_ac": 0.0, "half_life_est": None,
                "mean_reverting": False, "strength": 0.0, "sign": 0, "lag": 0,
                "stability": 0.0, "sample_size": n}
    r = returns(series)
    vals = [r[d] for d in sorted(r)]
    acs = {}
    for lag in range(1, max_lag + 1):
        xs = vals[:-lag] if lag else vals
        ys = vals[lag:]
        if len(xs) < 5:
            continue
        acs[lag] = _pearson(xs, ys)
    if not acs:
        return {"lag1_ac": 0.0, "best_lag": 0, "best_ac": 0.0, "half_life_est": None,
                "mean_reverting": False, "strength": 0.0, "sign": 0, "lag": 0,
                "stability": 0.0, "sample_size": n}
    lag1 = acs.get(1, 0.0)
    best_lag = max(acs, key=lambda k: abs(acs[k]))
    best_ac = acs[best_lag]
    half_life = None
    if 0 < lag1 < 0.999:
        half_life = round(math.log(0.5) / math.log(lag1), 2)
    mean_reverting = lag1 < 0
    return {"lag1_ac": round(lag1, 4), "best_lag": best_lag, "best_ac": round(best_ac, 4),
            "half_life_est": half_life, "mean_reverting": bool(mean_reverting),
            "strength": min(1.0, abs(best_ac)), "sign": 1 if best_ac >= 0 else -1,
            "lag": best_lag, "stability": round(max(0.0, 1.0 - abs(lag1)), 4),
            "sample_size": n}



def evaluate_pair(series_a: dict, series_b: dict, model: str = "linear",
                  max_lag: int = 10, lag: int | None = None) -> dict:
    """评估一条有向边 A→B (A 影响 B)。

    series_a / series_b: {日期: 值}。
    返回结构化评估结果 (含 model / strength / sign / lag / stability / metrics / params)。
    """
    series_a, series_b, resampled = _prepare_pair(series_a, series_b)
    aligned = align_series(series_a, series_b, max_lag)
    n = len(aligned)
    if n < 5:
        return {"model": model, "strength": 0.0, "sign": 0, "lag": 0,
                "stability": 0.0, "sample_size": n, "params": {},
                "metrics": {}, "insufficient_data": True, "resampled": resampled}

    ra = returns(series_a)
    rb = returns(series_b)
    result = {"model": model, "sample_size": n, "insufficient_data": False, "resampled": resampled}

    if model == "correlation":
        xs = [p[0] for p in aligned]
        ys = [p[1] for p in aligned]
        c = _pearson(xs, ys)
        result.update({"strength": abs(c), "sign": 1 if c >= 0 else -1, "lag": 0,
                       "stability": _stability(series_a, series_b, 0),
                       "params": {"pearson": round(c, 4)},
                       "metrics": {"pearson": round(c, 4)}})

    elif model == "lead_lag":
        ll = lead_lag(series_a, series_b, max_lag)
        result.update(ll)
        result["stability"] = _stability(series_a, series_b, ll["lag"])
        result["metrics"] = {"corr": round(ll["corr"], 4)}

    elif model == "vol_spillover":
        # 波动溢出: A 的波动 (|收益|) 对 B 的波动的影响
        va = {d: abs(v) for d, v in ra.items()}
        vb = {d: abs(v) for d, v in rb.items()}
        ll = lead_lag(va, vb, max_lag)
        result.update(ll)
        result["model"] = "vol_spillover"
        result["stability"] = _stability(va, vb, ll["lag"])
        result["metrics"] = {"vol_corr": round(ll["corr"], 4)}
        result["params"] = {"vol_corr": round(ll["corr"], 4)}

    elif model in ("linear", "momentum", "exp_decay", "var"):
        # 价格量纲差异大 -> 统一用收益率拟合, 得到无量纲弹性系数 (可跨品种比较)
        use_lag = lag if lag is not None else (1 if model in ("momentum", "var") else 0)
        if model == "linear":
            pairs = _lagged(ra, rb, use_lag)
            if len(pairs) < 5:
                pairs = [(ra[d], rb[d]) for d in sorted(set(ra) & set(rb))]
                use_lag = 0
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            a, b, r2 = _linear_fit(xs, ys)
            result.update({"lag": use_lag, "sign": 1 if b >= 0 else -1,
                           "stability": _stability(ra, rb, use_lag),
                           "params": {"a": round(a, 6), "b": round(b, 6), "r2": round(r2, 4)},
                           "metrics": {"r2": round(r2, 4)}})
            result["strength"] = min(1.0, abs(r2) * 1.2)

        elif model == "momentum":
            # B_t = a + b*A_(t-1) + c*B_(t-1): 扩散 + 自身动量
            dates = sorted(set(ra) & set(rb))
            rows = []
            for i, d in enumerate(dates):
                if i < use_lag or (i - 1) < 0:
                    continue
                rows.append((float(ra[dates[i - use_lag]]), float(rb[dates[i - 1]]), float(rb[d])))
            if len(rows) < 5:
                result.update({"strength": 0.0, "sign": 0, "lag": use_lag, "stability": 0.0,
                               "params": {}, "metrics": {}, "insufficient_data": True})
                return result
            _, c, _ = _linear_fit([r[1] for r in rows], [r[2] for r in rows])
            resid = [r[2] - c * r[1] for r in rows]
            _, b, r2 = _linear_fit([r[0] for r in rows], resid)
            result.update({"lag": use_lag, "sign": 1 if b >= 0 else -1,
                           "stability": _stability(ra, rb, use_lag),
                           "params": {"b": round(b, 6), "c": round(c, 6), "r2": round(r2, 4)},
                           "metrics": {"r2": round(r2, 4)}})
            result["strength"] = min(1.0, abs(r2) * 1.2)

        elif model == "exp_decay":
            pairs = _lagged(ra, rb, use_lag)
            if len(pairs) < 5:
                pairs = [(ra[d], rb[d]) for d in sorted(set(ra) & set(rb))]
                use_lag = 0
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            fit = exp_decay_fit(xs, ys, half_life=max(2, n // 5))
            result.update({"lag": use_lag, "sign": 1 if fit["b"] >= 0 else -1,
                           "stability": _stability(ra, rb, use_lag),
                           "params": {"a": round(fit["a"], 6), "b": round(fit["b"], 6),
                                      "r2": round(fit["r2"], 4), "half_life": max(2, n // 5)},
                           "metrics": {"r2": round(fit["r2"], 4)}})
            result["strength"] = min(1.0, abs(fit["r2"]) * 1.2)

        elif model == "var":
            # 双变量 VAR(1): B_t = a + b*A_(t-1) + c*B_(t-1); 用格兰杰式检验 A 是否
            # 对 B 有额外解释力 (对比受限模型 B_t = a + c*B_(t-1))
            dates = sorted(set(ra) & set(rb))
            rows = []
            for i, d in enumerate(dates):
                if i < use_lag or (i - 1) < 0:
                    continue
                rows.append((float(ra[dates[i - use_lag]]), float(rb[dates[i - 1]]), float(rb[d])))
            if len(rows) < 6:
                result.update({"strength": 0.0, "sign": 0, "lag": use_lag, "stability": 0.0,
                               "params": {}, "metrics": {}, "insufficient_data": True})
                return result
            _, c_restricted, r2_restricted = _linear_fit([r[1] for r in rows], [r[2] for r in rows])
            resid_restricted = [r[2] - (c_restricted * r[1] + 0.0) for r in rows]
            _, b_full, r2_full = _linear_fit([r[0] for r in rows], resid_restricted)
            inc = max(0.0, r2_full - r2_restricted)
            result.update({"lag": use_lag, "sign": 1 if b_full >= 0 else -1,
                           "stability": _stability(ra, rb, use_lag),
                           "params": {"b": round(b_full, 6), "c": round(c_restricted, 6),
                                      "r2_full": round(r2_full, 4),
                                      "r2_restricted": round(r2_restricted, 4),
                                      "incremental_r2": round(inc, 4)},
                           "metrics": {"incremental_r2": round(inc, 4),
                                       "granger_style": bool(inc > 0.01)}})
            result["strength"] = min(1.0, inc * 4 + abs(r2_full) * 0.8)

    elif model == "rolling_corr":
        window = max(10, min(60, n // 8))
        rc = rolling_corr(series_a, series_b, window=window, max_lag=min(5, max_lag))
        result.update({"lag": rc["lag"], "sign": rc["sign"], "strength": rc["strength"],
                       "stability": rc["stability"],
                       "params": {"window": window, "mean_corr": rc["mean"], "std": rc["std"],
                                  "min": rc["min"], "max": rc["max"], "trend": rc["trend"]},
                       "metrics": {"mean_corr": rc["mean"], "corr_std": rc["std"], "trend": rc["trend"]},
                       "curve": rc["curve"]})

    elif model == "regime_shift":
        window = max(10, min(40, n // 10))
        rs = regime_shift(series_a, series_b, window=window)
        result.update({"lag": rs["lag"], "sign": rs["sign"], "strength": rs["strength"],
                       "stability": rs["stability"],
                       "params": {"break_date": rs["break_date"], "shift_type": rs["shift_type"],
                                  "delta": rs["delta"], "pre_corr": rs["pre_corr"],
                                  "post_corr": rs["post_corr"]},
                       "metrics": {"shift_type": rs["shift_type"], "delta": rs["delta"],
                                   "pre_corr": rs["pre_corr"], "post_corr": rs["post_corr"],
                                   "break_date": rs["break_date"]}})

    elif model == "event_study":
        es = event_study(series_a, series_b, window=5, threshold=2.0)
        result.update({"lag": es["lag"], "sign": es["sign"], "strength": es["strength"],
                       "stability": es["stability"],
                       "params": {"window": 5, "threshold": 2.0, "event_count": es["event_count"],
                                  "avg_response": es["avg_response"], "hit_rate": es["hit_rate"]},
                       "metrics": {"event_count": es["event_count"],
                                   "avg_response": es["avg_response"], "hit_rate": es["hit_rate"]},
                       "events": es["events"]})

    elif model == "self_corr":
        # 自相关: 评估 B 自身的动量/均值回归 (A 不起作用, 但保留 A→B 契约)
        sc = self_corr(series_b, max_lag=max_lag)
        result.update({"lag": sc["lag"], "sign": sc["sign"], "strength": sc["strength"],
                       "stability": sc["stability"],
                       "params": {"lag1_ac": sc["lag1_ac"], "best_lag": sc["best_lag"],
                                  "best_ac": sc["best_ac"], "half_life_est": sc["half_life_est"],
                                  "mean_reverting": sc["mean_reverting"]},
                       "metrics": {"lag1_ac": sc["lag1_ac"], "best_ac": sc["best_ac"],
                                   "mean_reverting": sc["mean_reverting"]}})

    else:
        raise ValueError(f"unknown model: {model}")

    result["modeled_at"] = _now()
    return result


def evaluate_all(panel: dict, pairs: list[tuple] | None = None,
                 model: str = "linear", max_lag: int = 10,
                 lag: int | None = None) -> list[dict]:
    """对整张关联矩阵求值。

    panel: {维度key: {日期: 值}}
    pairs: [(from_dim, to_dim), ...]；缺省时对 panel 所有维度两两求值 (排除自环)。
    返回: 每条边一个评估结果 (方向敏感)。
    """
    from reserve.relations.frame import ordered_pairs, pair_key, expand_targets

    dims = expand_targets(list(panel.keys()))
    if pairs is None:
        pairs = ordered_pairs(dims)
    results = []
    for a, b in pairs:
        sa = panel.get(a.key if hasattr(a, "key") else str(a), {})
        sb = panel.get(b.key if hasattr(b, "key") else str(b), {})
        if not sa or not sb:
            continue
        res = evaluate_pair(sa, sb, model=model, max_lag=max_lag, lag=lag)
        res["edge"] = pair_key(a, b)
        res["direction"] = res["edge"]
        res["from"] = a.to_dict() if hasattr(a, "to_dict") else parse_dim(a).to_dict()
        res["to"] = b.to_dict() if hasattr(b, "to_dict") else parse_dim(b).to_dict()
        results.append(res)
    return results


def parse_dim(d):
    from reserve.relations.dims import parse_dim as _pd
    return _pd(d)
