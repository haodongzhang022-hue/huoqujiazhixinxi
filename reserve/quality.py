"""reserve/quality.py — 内容质量评估模块（"每天获取的内容质量怎么样了"）

回答用户核心诉求：**每天获取的内容质量如何评估**。

本模块提供三级质量视角：
  1. 快照质量 (snapshot)      —— 评估一次采集（快照 JSON）的完整度/新鲜度/丰富度
  2. 储备库质量 (reserve)     —— 评估当前储备库整体质量（结构完整度/索引覆盖/分类健康）
  3. 趋势与报告 (report/trend) —— 对多日快照做纵向趋势分析，产出每日质量报告

质量维度设计（0~100 综合分）：
  - completeness  完整性: 字段缺失率（description/topics/language/license 等关键字段）
  - freshness     新鲜度: 当日新仓库占比、7d 有增量仓库占比、采集时间
  - richness      丰富度: 分类覆盖、去重后唯一仓库数、功能索引覆盖率
  - index_health  索引健康: function_tags / function_summary / use_case / review 覆盖率
  - decision_health 决策健康: 分类分布合理性、action 候选占比、review 通过率

输出:
  - assess_snapshot(path)      -> 快照质量报告 dict
  - assess_store(store=None)   -> 储备库质量报告 dict
  - assess_trend(days=7)       -> 多日趋势报告 dict
  - write_report(report, path) -> 持久化质量报告（data/reports/YYYY-MM-DD.json）
  - report_summary(report)     -> 人类可读摘要

CLI 用法:
  python -m reserve.quality --snapshot pipeline/data/snapshots/2026-08-09.json
  python -m reserve.quality --store
  python -m reserve.quality --trend --days 7
  python -m reserve.quality --report            # 今日快照 + 储备库 + 趋势 综合报告
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reserve.store import ReserveStore

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "data" / "reports"

# 质量评分权重
WEIGHTS = {
    "completeness": 0.30,
    "freshness": 0.25,
    "richness": 0.20,
    "index_health": 0.15,
    "decision_health": 0.10,
}

# 关键字段完整度检查
KEY_FIELDS = ["full_name", "description", "language", "stars", "created_at", "url"]
INDEX_FIELDS = ["function_tags", "function_summary", "use_case"]

# 质量分分级
GRADE_BANDS = [
    (90, "A", "优秀: 内容质量高, 可直接使用"),
    (75, "B", "良好: 质量达标, 建议修复少量缺项"),
    (60, "C", "一般: 有较多缺项, 建议检查采集/索引配置"),
    (0, "D", "较差: 数据异常, 需要自愈合干预"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def grade_for(score: float) -> dict:
    for threshold, grade, desc in GRADE_BANDS:
        if score >= threshold:
            return {"grade": grade, "desc": desc}
    return {"grade": "D", "desc": GRADE_BANDS[-1][2]}


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def _safe_int(v, default=0) -> int:
    try:
        return int(v or default)
    except (TypeError, ValueError):
        return default


# ============================================================
# 快照质量评估
# ============================================================

def assess_snapshot(path: str | Path, store: ReserveStore | None = None) -> dict:
    """评估一次采集快照的质量。

    支持 {repos: [...]} / {items: [...]} / 列表 结构（兼容两版 fetch 输出）。
    """
    path = Path(path)
    if not path.exists():
        return {"error": f"snapshot not found: {path}", "path": str(path)}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"snapshot unreadable: {e}", "path": str(path)}

    repos = []
    if isinstance(data, list):
        repos = data
    elif isinstance(data, dict):
        repos = data.get("repos") or data.get("items") or []
    repos = [r for r in repos if r]
    total = len(repos)

    # 字段兼容: fetch v1 (stargazers_count/forks_count) 与 v2 (stars/forks) 并存
    def _val(r: dict, *keys):
        for k in keys:
            v = r.get(k)
            if v is not None:
                return v
        return None

    def _license_of(r: dict):
        lic = r.get("license")
        if isinstance(lic, dict):
            return lic.get("spdx_id")
        return lic

    # 完整性: 关键字段缺失统计
    missing: dict[str, int] = {}
    for field in KEY_FIELDS:
        if field == "stars":
            missing[field] = sum(1 for r in repos if _val(r, "stars", "stargazers_count") is None)
        elif field == "full_name":
            missing[field] = sum(1 for r in repos if not (r.get("full_name") or r.get("repo_id")))
        elif field == "url":
            missing[field] = sum(1 for r in repos if not (r.get("url") or r.get("html_url")))
        else:
            missing[field] = sum(1 for r in repos if not r.get(field))
    # license 缺失单独记录（宽松: 允许部分仓库无 license, 但全缺要提示）
    missing["license"] = sum(1 for r in repos if not _license_of(r))

    # 丰富度
    unique = len({r.get("full_name") or r.get("repo_id") for r in repos})
    categories = [r.get("category") or "" for r in repos]
    cat_counter = Counter(c for c in categories if c)
    empty_cats = sum(1 for c in cat_counter.values() if c == 0)
    # category 字段缺失计数
    no_category = sum(1 for r in repos if not r.get("category"))

    # 新鲜度
    new_week = sum(1 for r in repos if r.get("is_new_this_week"))
    has_delta_7d = sum(1 for r in repos if _val(r, "stars_delta_7d") is not None and _safe_int(_val(r, "stars_delta_7d")) > 0)
    has_delta_24h = sum(1 for r in repos if _val(r, "stars_delta_24h") is not None and _safe_int(_val(r, "stars_delta_24h")) > 0)
    action_cand = sum(1 for r in repos if r.get("action_candidate"))

    # 功能索引覆盖率
    has_tags = sum(1 for r in repos if r.get("function_tags"))
    has_summary = sum(1 for r in repos if r.get("function_summary"))
    llm_indexed = sum(1 for r in repos if r.get("index_source") == "llm")

    # 数据合理性: stars 为 0 或缺失
    zero_stars = sum(1 for r in repos if _safe_int(_val(r, "stars", "stargazers_count")) <= 0)

    # ----- 维度分 -----
    # 完整性 (满分 100): 关键字段缺失率 + license 覆盖率
    key_missing_pct = _pct(sum(missing.get(f, 0) for f in KEY_FIELDS), total * len(KEY_FIELDS))
    license_missing_pct = _pct(missing.get("license", 0), total)
    completeness = round(100 - key_missing_pct - 0.5 * license_missing_pct, 1)

    # 新鲜度
    fresh_ratio = _pct(new_week, total)
    delta_ratio = _pct(has_delta_7d, total)
    freshness = round(0.5 * fresh_ratio + 0.5 * min(100, delta_ratio * 1.5), 1)

    # 丰富度
    unique_ratio = _pct(unique, total) if total else 0
    cat_coverage = _pct(len(cat_counter), 8)  # 8 生态域
    no_cat_pct = _pct(no_category, total)
    richness = round(0.35 * unique_ratio + 0.35 * cat_coverage + 0.30 * (100 - no_cat_pct), 1)

    # 索引健康
    tags_ratio = _pct(has_tags, total)
    summary_ratio = _pct(has_summary, total)
    index_health = round(0.6 * tags_ratio + 0.4 * summary_ratio, 1)

    # 决策健康 (快照层只有候选标记, 储备库层才有分类)
    decision_health = round(min(100, 40 + action_cand * 60 / max(1, total)), 1)

    score = round(
        WEIGHTS["completeness"] * completeness
        + WEIGHTS["freshness"] * freshness
        + WEIGHTS["richness"] * richness
        + WEIGHTS["index_health"] * index_health
        + WEIGHTS["decision_health"] * decision_health,
        1,
    )

    issues = []
    if total == 0:
        issues.append("采集为空: 0 个仓库, 管道可能故障")
    if empty_cats > 0 or (cat_counter and len(cat_counter) < 4):
        issues.append(f"分类覆盖不足: 仅 {len(cat_counter)} 个分类有数据 (期望 8)")
    if no_category > 0:
        issues.append(f"{no_category} 个仓库缺少分类字段")
    if fresh_ratio < 10:
        issues.append(f"新仓库占比过低 ({fresh_ratio}%), 采集可能未覆盖 T4 新仓库扫描")
    if has_delta_7d == 0 and has_delta_24h == 0:
        issues.append("无任何增量数据 (delta 全为 0/None), 冷启动或快照基线缺失")
    if zero_stars > total * 0.3:
        issues.append(f"{zero_stars} 个仓库 stars<=0, 数据疑似异常")
    if missing.get("license", 0) > total * 0.5:
        issues.append("超过一半仓库缺少 license 信息")

    return {
        "type": "snapshot",
        "path": str(path),
        "date": path.stem,
        "assessed_at": now_iso(),
        "score": score,
        "grade": grade_for(score),
        "dimensions": {
            "completeness": completeness,
            "freshness": freshness,
            "richness": richness,
            "index_health": index_health,
            "decision_health": decision_health,
        },
        "stats": {
            "total": total,
            "unique": unique,
            "new_this_week": new_week,
            "has_delta_7d": has_delta_7d,
            "has_delta_24h": has_delta_24h,
            "action_candidates": action_cand,
            "llm_indexed": llm_indexed,
            "categories": dict(cat_counter.most_common()),
            "missing_fields": missing,
            "zero_stars": zero_stars,
        },
        "issues": issues,
        "recommendation": _snapshot_recommendation(score, issues),
    }


def _snapshot_recommendation(score: float, issues: list[str]) -> str:
    if score >= 90:
        return "质量优秀, 保持当前采集配置"
    if score >= 75:
        return f"质量良好。建议处理: {'; '.join(issues[:3]) if issues else '无重大缺项'}"
    if score >= 60:
        return f"质量一般, 需要关注: {'; '.join(issues[:4]) if issues else '评分偏低原因待查'}"
    return f"质量较差, 建议立即自愈合: {'; '.join(issues[:5]) if issues else '检查管道配置'}; 可执行 python -m reserve.self_heal"


# ============================================================
# 储备库质量评估
# ============================================================

def assess_store(store: ReserveStore | None = None) -> dict:
    """评估储备库（LanceDB repo_reserve 表）整体质量。"""
    store = store or ReserveStore()
    repos = store.all_repos(limit=100000)
    total = len(repos)

    if total == 0:
        return {
            "type": "store",
            "assessed_at": now_iso(),
            "score": 0.0,
            "grade": grade_for(0),
            "stats": {"total": 0},
            "issues": ["储备库为空, 尚未入库任何仓库"],
            "recommendation": "先运行 python -m reserve.ingest 入库数据",
        }

    # 索引覆盖
    has_tags = sum(1 for r in repos if r.get("function_tags"))
    has_summary = sum(1 for r in repos if r.get("function_summary"))
    has_use_case = sum(1 for r in repos if r.get("use_case"))
    llm_indexed = sum(1 for r in repos if r.get("index_source") == "llm")

    # 分类分布
    decisions = Counter(r.get("category_decision") or "none" for r in repos)
    categories = Counter(r.get("category") or "unknown" for r in repos)

    # review 覆盖
    reviewed = sum(1 for r in repos if r.get("review"))
    review_approved = sum(1 for r in repos if r.get("review_status") == "approved")
    review_pending = sum(1 for r in repos if r.get("review_status") == "pending")

    # 增量新鲜度
    has_delta = sum(1 for r in repos if r.get("stars_delta_7d") is not None and r.get("stars_delta_7d", 0) > 0)

    # ----- 维度分 -----
    index_health = round(0.4 * _pct(has_tags, total) + 0.3 * _pct(has_summary, total)
                         + 0.3 * _pct(has_use_case, total), 1)
    # 决策健康: 有 action 或 reserve 占比 + review 通过率
    useful = decisions.get("action", 0) + decisions.get("reserve", 0)
    useful_ratio = _pct(useful, total)
    review_ratio = _pct(review_approved, reviewed) if reviewed else 0
    decision_health = round(0.6 * useful_ratio + 0.4 * (100 if reviewed == 0 else review_ratio), 1)
    richness = round(min(100, total * 100 / 200) * 0.5 + _pct(len(categories), 8) * 0.5, 1)
    freshness = round(min(100, 50 + has_delta * 50 / max(1, total)), 1)
    # 完整性: 关键字段
    missing_desc = sum(1 for r in repos if not r.get("description"))
    completeness = round(100 - _pct(missing_desc, total), 1)

    score = round(
        WEIGHTS["completeness"] * completeness
        + WEIGHTS["freshness"] * freshness
        + WEIGHTS["richness"] * richness
        + WEIGHTS["index_health"] * index_health
        + WEIGHTS["decision_health"] * decision_health,
        1,
    )

    issues = []
    if index_health < 50:
        issues.append(f"功能索引覆盖率低 ({index_health}%), 建议配置 LLM 或检查 enrich 步骤")
    if useful_ratio < 20:
        issues.append(f"可用决策占比低 (action+reserve 仅 {useful_ratio}%), 分类规则可能过严")
    if decisions.get("ignore", 0) > total * 0.5:
        issues.append(f"ignore 占比过高 ({decisions.get('ignore', 0)}/{total}), 检查采集与打分规则")
    if total < 30:
        issues.append(f"储备库数据量偏少 ({total} 条), 建议持续积累")
    if review_pending > 0:
        issues.append(f"{review_pending} 条 review 待人工审核 (python -m reserve.review queue)")

    return {
        "type": "store",
        "assessed_at": now_iso(),
        "score": score,
        "grade": grade_for(score),
        "dimensions": {
            "completeness": completeness,
            "freshness": freshness,
            "richness": richness,
            "index_health": index_health,
            "decision_health": decision_health,
        },
        "stats": {
            "total": total,
            "decisions": dict(decisions),
            "categories": dict(categories.most_common()),
            "index_coverage": {
                "function_tags": _pct(has_tags, total),
                "function_summary": _pct(has_summary, total),
                "use_case": _pct(has_use_case, total),
                "llm_indexed": _pct(llm_indexed, total),
            },
            "review": {
                "reviewed": reviewed,
                "approved": review_approved,
                "pending": review_pending,
            },
            "has_delta_7d": _pct(has_delta, total),
        },
        "issues": issues,
        "recommendation": _store_recommendation(score, issues),
    }


def _store_recommendation(score: float, issues: list[str]) -> str:
    if score >= 90:
        return "储备库质量优秀, 生态储备健康"
    if score >= 75:
        return f"储备库质量良好。建议: {'; '.join(issues[:3]) if issues else '持续积累'}"
    if score >= 60:
        return f"储备库质量一般。建议处理: {'; '.join(issues[:4])}"
    return f"储备库质量较差, 需要干预: {'; '.join(issues[:5])}; 建议配置 LLM 提升索引质量并检查采集管道"


# ============================================================
# 多日趋势
# ============================================================

def assess_trend(days: int = 7, snapshots_dir: str | Path | None = None) -> dict:
    """对最近 N 天的快照做纵向质量趋势分析。"""
    snap_dir = Path(snapshots_dir) if snapshots_dir else ROOT / "pipeline" / "data" / "snapshots"
    if not snap_dir.exists():
        return {"error": f"snapshots dir not found: {snap_dir}", "trend": []}

    import re as _re
    today = datetime.now(timezone.utc).date()
    dates = {today - timedelta(days=i): None for i in range(days)}
    trend = []
    # 扫描目录内所有快照, 兼容 demo-YYYY-MM-DD / YYYY-MM-DD 命名
    for p in sorted(snap_dir.glob("*.json"), reverse=True):
        m = _re.search(r"(\d{4}-\d{2}-\d{2})", p.stem)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d not in dates:
            continue
        report = assess_snapshot(p)
        if "error" in report:
            continue
        trend.append({
            "date": report["date"],
            "score": report["score"],
            "grade": report["grade"]["grade"],
            "total": report["stats"]["total"],
            "unique": report["stats"]["unique"],
            "new_this_week": report["stats"]["new_this_week"],
            "action_candidates": report["stats"]["action_candidates"],
            "index_health": report["dimensions"]["index_health"],
            "freshness": report["dimensions"]["freshness"],
        })

    trend.sort(key=lambda x: x["date"])
    if not trend:
        return {"error": f"no snapshots in {snap_dir}", "trend": []}

    avg_score = round(sum(t["score"] for t in trend) / len(trend), 1)
    scores = [t["score"] for t in trend]
    delta = round(scores[-1] - scores[0], 1) if len(scores) > 1 else 0
    direction = "up" if delta > 1 else ("down" if delta < -1 else "flat")

    return {
        "type": "trend",
        "assessed_at": now_iso(),
        "days": len(trend),
        "avg_score": avg_score,
        "latest_score": scores[-1] if scores else 0,
        "delta": delta,
        "direction": direction,
        "points": trend,
        "recommendation": _trend_recommendation(direction, delta, avg_score),
    }


def _trend_recommendation(direction: str, delta: float, avg_score: float) -> str:
    if direction == "down":
        return f"质量呈下降趋势 (Δ{delta}), 建议执行自愈合: python -m reserve.self_heal"
    if avg_score < 60:
        return f"平均质量偏低 ({avg_score}), 建议检查采集配置/LLM 索引/分类规则"
    if direction == "up":
        return f"质量呈上升趋势 (Δ{delta:+}), 保持当前配置"
    return f"质量稳定 (avg {avg_score}), 持续观察"


# ============================================================
# 综合报告
# ============================================================

def build_report(days: int = 7, store: ReserveStore | None = None,
                 snapshot: str | Path | None = None) -> dict:
    """生成今日综合质量报告（快照 + 储备库 + 趋势）。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 快照: 优先指定, 否则今日快照
    snapshot_report = None
    if snapshot:
        snapshot_report = assess_snapshot(snapshot)
    else:
        snap = ROOT / "pipeline" / "data" / "snapshots" / f"{today}.json"
        if snap.exists():
            snapshot_report = assess_snapshot(snap)
        else:
            snapshot_report = {"error": f"今日快照不存在: {snap}", "type": "snapshot"}

    store_report = assess_store(store)
    trend_report = assess_trend(days=days)

    scores = [r.get("score") for r in [snapshot_report, store_report, trend_report]
              if isinstance(r.get("score"), (int, float))]
    overall = round(sum(scores) / len(scores), 1) if scores else 0.0

    return {
        "type": "report",
        "date": today,
        "generated_at": now_iso(),
        "overall_score": overall,
        "overall_grade": grade_for(overall),
        "snapshot": snapshot_report,
        "store": store_report,
        "trend": trend_report,
        "recommendation": _report_recommendation(snapshot_report, store_report, trend_report),
    }


def _report_recommendation(snapshot: dict, store: dict, trend: dict) -> str:
    recs = []
    for part in (snapshot, store, trend):
        if isinstance(part, dict) and part.get("recommendation"):
            recs.append(part["recommendation"])
    return "；".join(recs) if recs else "整体质量正常"


def write_report(report: dict, path: str | Path | None = None) -> Path:
    """持久化质量报告到 data/reports/YYYY-MM-DD.json。"""
    path = Path(path) if path else REPORT_DIR / f"{report.get('date', 'report')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[quality] report written -> {path}")
    return path


def report_summary(report: dict) -> str:
    """人类可读质量报告摘要。"""
    lines = [f"📊 质量报告 {report.get('date', '')} | 综合分 {report.get('overall_score', '-')} "
             f"({report.get('overall_grade', {}).get('grade', '-')})"]
    for key, label in [("snapshot", "快照"), ("store", "储备库"), ("trend", "趋势")]:
        part = report.get(key) or {}
        if "error" in part:
            lines.append(f"- {label}: {part['error']}")
        elif part.get("score") is not None:
            lines.append(f"- {label}: {part.get('score')} 分 ({part.get('grade', {}).get('grade', '-')})")
            if part.get("issues"):
                lines.append(f"  ⚠️ {part['issues'][0]}")
    if report.get("recommendation"):
        lines.append(f"💡 建议: {report['recommendation']}")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="内容质量评估")
    parser.add_argument("--snapshot", default=None, help="评估指定快照 JSON")
    parser.add_argument("--store", action="store_true", help="评估储备库")
    parser.add_argument("--trend", action="store_true", help="多日趋势")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--report", action="store_true", help="生成今日综合报告并写入 data/reports/")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    if args.report:
        report = build_report(days=args.days)
        write_report(report)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(report_summary(report))
        return 0

    if args.snapshot:
        rep = assess_snapshot(args.snapshot)
    elif args.store:
        rep = assess_store()
    elif args.trend:
        rep = assess_trend(days=args.days)
    else:
        parser.print_help()
        return 1

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    else:
        if "error" in rep:
            print(f"❌ {rep['error']}")
        else:
            print(f"📊 质量分 {rep['score']} ({rep['grade']['grade']}) | {rep['grade']['desc']}")
            for k, v in rep.get("dimensions", {}).items():
                print(f"  - {k}: {v}")
            if rep.get("issues"):
                print("⚠️ 问题:")
                for i in rep["issues"]:
                    print(f"  - {i}")
            if rep.get("recommendation"):
                print(f"💡 建议: {rep['recommendation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
