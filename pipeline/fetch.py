"""每日开源项目采集主管道 —— wvb-cc-radar fetch 模型改造版 (fetch.py)。

改造说明 (对照原版 wvb-cc-radar/scripts/fetch.py):
  1. 分类泛化        : Claude Code 专属 8 类 → 通用技术生态 8 类
                       (mcp-servers / ai-agents / rag-kb / agent-orchestration /
                        llm-prompts / ai-dev-tools / data-infra / developer-tools)
  2. 语言本地化      : 韩语翻译 (description_ko) → 中文功能索引占位 (description_zh)
                       LLM enrichment 在本模块保持「无 key 可降级跳过」，
                       后续由 classifier/enrich 步骤接入 LLM 生成 function_tags。
  3. schema 对齐     : 输出字段对齐调研报告 §5.2 LanceDB repo_reserve 表:
                       full_name / description / language / topics / stars /
                       stars_delta_24h / stars_delta_7d / created_at /
                       first_seen_at / source / category / is_new_this_week
  4. 增量计算        : 保留原版 24h delta (昨日快照) + 7d delta (周基线) 双基线
  5. 输出            : data/snapshots/YYYY-MM-DD.json (每日快照, 供入库/去重)

v2.1 (条件触发引擎联动):
  - 冷启动推断  : 无历史快照时, 新仓库 stars_delta_7d ≈ stars, 老仓库不猜 →
                   首次运行也能激活 action 生态升级路径 (action_candidate 标记)
  - T4 新仓库扫描: config.py 每分类新增 created:>7d 查询, 主动捕获当周新项目
  - needs 回路   : 对接本地 pending_needs, 新项目入库时自动粗匹配未满足需求
                   (matched_needs 回填, 细评分由 classifier/本地 trigger 完成)

用法:
  python -m pipeline.fetch [--limit N] [--dry-run]
  python -m pipeline.fetch --needs-file needs.json   # 指定 pending_needs 文件

Env:
  GITHUB_TOKEN 可选 —— 不设则匿名 60 req/hr (8 类全量约 45+ 请求, 请耐心)
  PIPELINE_NEEDS_FILE 可选 —— pending_needs JSON 路径 (默认 pipeline/data/needs.json)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, github_client
from .config import categories as build_categories

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "pipeline" / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SEED_DIR = DATA_DIR / "seeds"
NEEDS_FILE = DATA_DIR / "needs.json"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
SEED_DIR.mkdir(parents=True, exist_ok=True)

# needs 粗匹配阈值: 关键词命中比例 >= 0.5 视为命中 (细评分由 classifier/trigger 做)
NEED_MATCH_THRESHOLD = 0.5


# ============================================================
# seed allowlist 加载
# ============================================================

def load_seeds() -> dict[str, list[str]]:
    """加载 data/seeds/*.json 中的显式 allowlist。

    每类一个文件 {category}.json, 结构: {"repos": ["owner/name", ...]}
    对应 wvb-cc-radar 的 claude-code-curated / applications-seed 机制。
    """
    seeds: dict[str, list[str]] = {}
    for f in SEED_DIR.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            seeds[f.stem] = [r for r in raw.get("repos", []) if r]
        except Exception as e:
            print(f"[seeds] failed to read {f.name}: {e}", file=sys.stderr)
    return seeds


# ============================================================
# pending_needs 加载 (双向生长回路, v2.1)
# ============================================================

def load_pending_needs(path: str | None = None) -> list[dict]:
    """加载本地 pending_needs (未满足需求列表, 对接 /api/v1/needs)。

    文件结构: {"needs": [{"id", "text", "keywords": [...]}, ...]}
    或直接是列表。可通过 --needs-file / PIPELINE_NEEDS_FILE 覆盖。
    文件不存在时返回 [] (回路留待本地 trigger 引擎接管, 不影响采集)。
    """
    p = Path(path) if path else Path(os.environ.get("PIPELINE_NEEDS_FILE", "")) if os.environ.get("PIPELINE_NEEDS_FILE") else NEEDS_FILE
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        needs = raw.get("needs", raw) if isinstance(raw, dict) else raw
        print(f"[needs] loaded {len(needs)} from {p}")
        return needs if isinstance(needs, list) else []
    except Exception as e:
        print(f"[needs] failed to read {p}: {e}", file=sys.stderr)
        return []


# ============================================================
# 仓库字段抽取 (对齐 LanceDB repo_reserve schema)
# ============================================================

def extract_repo(item: dict) -> dict:
    full_name = item["full_name"]
    repo = {
        "repo_id": full_name,  # 唯一键 = full_name (与本地 repo_reserve 表对齐)
        "full_name": full_name,
        "name": item["name"],
        "owner": item["owner"]["login"],
        "url": item["html_url"],
        "description": item.get("description"),
        "homepage": item.get("homepage"),
        "language": item.get("language"),
        "topics": item.get("topics", []) or [],
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "created_at": item["created_at"],
        "pushed_at": item.get("pushed_at"),
        "updated_at": item.get("updated_at"),
        "archived": item.get("archived", False),
        "license": (item.get("license") or {}).get("spdx_id"),
        # 增量指标 (由历史快照计算, 无历史则缺省)
        "stars_delta_24h": None,
        "stars_delta_7d": None,
        "forks_delta_7d": None,
        "is_new_this_week": is_new_this_week(item["created_at"]),
        # v2.1 action 生态升级路径: 冷启动推断 + 候选标记
        #   - 无历史快照时 (冷启动/首次运行): 新仓库 delta ≈ stars (近似), 老仓库 delta=None
        #   - action_candidate: True 表示值得交给 classifier/trigger 评估是否进 action
        "action_candidate": False,
        "delta_source": "none",  # none / coldstart / snapshot24h / snapshot7d
        # v2.1 对接本地 pending_needs 双向生长回路 (匹配结果由 needs 侧回填)
        "matched_needs": [],
        "matched_scores": [],
        # 功能索引 (LLM enrichment 步骤填充, 本模块降级为占位)
        "description_zh": None,
        "function_tags": [],
        "function_summary": None,
        "use_case": None,
        # 元信息
        "source": ["wvb-radar-fetch"],
        "category": None,   # 由分类循环填充
        "first_seen_at": datetime.now(timezone.utc).isoformat(),
    }
    return repo


def is_new_this_week(created_at: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created).days <= 7
    except Exception:
        return False


# ============================================================
# 历史快照加载 (增量指标基线)
# ============================================================

def load_prior_snapshots() -> tuple[dict[str, dict], dict[str, dict], int, int]:
    """加载昨日快照 (24h delta 基线) + 最近 7 天最旧快照 (7d delta 基线)。

    对应 wvb-cc-radar 的 load_prior_translations + load_weekly_baseline。
    返回 (昨日快照 {full_name: repo}, 周基线 {full_name: {stars, forks}}, 周窗口天数, 已有快照数)
    """
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    yesterday_stars: dict[str, dict] = {}
    weekly_candidates: list[tuple[int, Path]] = []
    snapshot_count = 0
    for delta_days in range(7, 0, -1):
        d = today - timedelta(days=delta_days)
        p = SNAPSHOT_DIR / f"{d.strftime('%Y-%m-%d')}.json"
        if not p.exists():
            continue
        snapshot_count += 1
        try:
            with open(p, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except Exception as e:
            print(f"[snapshot] failed to read {p.name}: {e}", file=sys.stderr)
            continue
        if d == yesterday:
            for r in snap.get("repos", []):
                yesterday_stars[r["full_name"]] = r
        weekly_candidates.append((delta_days, p))

    weekly_baseline: dict[str, dict] = {}
    weekly_window_days = 0
    if weekly_candidates:
        delta_days, path = max(weekly_candidates, key=lambda c: c[0])
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            for r in snap.get("repos", []):
                weekly_baseline[r["full_name"]] = {
                    "stars": r.get("stars", 0),
                    "forks": r.get("forks", 0),
                }
            weekly_window_days = delta_days
        except Exception as e:
            print(f"[snapshot] weekly baseline failed {path.name}: {e}", file=sys.stderr)
    return yesterday_stars, weekly_baseline, weekly_window_days, snapshot_count


def apply_deltas(repo: dict, yesterday_stars: dict, weekly_baseline: dict, weekly_window_days: int) -> None:
    """增量指标计算 + 冷启动推断 + action_candidate 标记 (v2.1)。

    优先用历史快照算真实 delta (24h/7d 双基线)；
    无历史快照时 (冷启动/首次运行):
      - is_new_this_week 新仓库 → stars_delta_7d ≈ stars (近似增量, 标记 coldstart)
      - 老仓库 → delta=None (无法推断, 不标 action)
    action_candidate: 新仓库 或 有真实增量且增长为正 → True, 交给 classifier/trigger 评估。
    """
    fn = repo["full_name"]
    prev = yesterday_stars.get(fn)
    if prev is not None:
        repo["stars_delta_24h"] = repo["stars"] - prev.get("stars", repo["stars"])
        repo["delta_source"] = "snapshot24h"

    base = weekly_baseline.get(fn)
    if base is not None and weekly_window_days > 0:
        repo["stars_delta_7d"] = repo["stars"] - base["stars"]
        repo["forks_delta_7d"] = repo["forks"] - base["forks"]
        repo["delta_window_days"] = weekly_window_days
        repo["delta_source"] = repo["delta_source"] if repo["delta_source"] != "none" else "snapshot7d"

    # 冷启动推断: 无历史基线 + 新仓库 → delta_7d ≈ stars (当前累计 stars 即一周内增量下限)
    if base is None and weekly_window_days == 0 and repo.get("is_new_this_week"):
        repo["stars_delta_7d"] = repo["stars"]
        repo["delta_source"] = "coldstart"

    # action 生态升级候选: 新仓库 / 有正增量
    d7 = repo.get("stars_delta_7d") or 0
    d24 = repo.get("stars_delta_24h") or 0
    repo["action_candidate"] = bool(repo.get("is_new_this_week") or d7 > 0 or d24 > 0)


def match_pending_needs(repos: list[dict], needs: list[dict]) -> None:
    """对接本地 pending_needs 双向生长回路 (v2.1)。

    新项目入库时自动重匹配未满足需求。本函数在 fetch 输出侧做一次**粗匹配**:
    - 把 pending_needs 的关键词/embedding 与仓库 名+描述+topics 比对;
    - 命中则写入 repo['matched_needs'] / matched_scores, 并回填 need['matched_repos'];
    - 细粒度评分由 classifier / 本地 trigger 引擎完成, 本函数只保证回路导通。

    needs 结构: [{"id", "text", "keywords": [...], ...}] (兼容本地 /api/v1/needs)
    """
    for repo in repos:
        haystack = " ".join([
            repo.get("name", ""),
            repo.get("full_name", ""),
            repo.get("description") or "",
            " ".join(repo.get("topics", []) or []),
        ]).lower()
        for need in needs:
            kws = [k.lower() for k in (need.get("keywords") or []) if k]
            if not kws:
                continue
            hits = sum(1 for k in kws if k in haystack)
            if hits == 0:
                continue
            score = round(hits / len(kws), 3)
            if score >= NEED_MATCH_THRESHOLD:
                repo.setdefault("matched_needs", []).append(need.get("id"))
                repo.setdefault("matched_scores", []).append(score)
                need.setdefault("matched_repos", []).append({
                    "full_name": repo["full_name"],
                    "score": score,
                })


# ============================================================
# 采集主流程
# ============================================================

def fetch(limit: int | None = None, dry_run: bool = False, needs_file: str | None = None) -> dict:
    auth = bool(github_client.GITHUB_TOKEN)
    print(f"[fetch] start | GitHub={'authenticated' if auth else 'ANONYMOUS(60/hr)'}")

    seeds = load_seeds()
    cats = build_categories(seeds)
    yesterday_stars, weekly_baseline, weekly_window_days, snapshot_count = load_prior_snapshots()
    print(
        f"[fetch] seeds={sum(len(v) for v in seeds.values())} | "
        f"snapshots={snapshot_count} | yesterday={len(yesterday_stars)} repos | "
        f"weekly_window={weekly_window_days}d"
    )

    all_repos: dict[str, dict] = {}
    categories_result = []
    rate_remaining: int | None = None

    for cat in cats:
        per_query = max(cat["top_n"], 30)
        merged: dict[str, dict] = {}

        # 1) Search 查询 (T1/T2/T3)
        for q in cat["queries"]:
            try:
                items, hdrs = github_client.search_repos(q, per_page=per_query)
                if hdrs.get("X-RateLimit-Remaining"):
                    rate_remaining = int(hdrs["X-RateLimit-Remaining"])
            except Exception as e:
                print(f"    [fetch] FAIL search: {e}", file=sys.stderr)
                items = []
            for item in items:
                fn = item["full_name"]
                if fn not in merged or item["stargazers_count"] > merged[fn]["stargazers_count"]:
                    merged[fn] = item
            github_client.sleep_between(auth)

        # 2) seed allowlist 直连 (若有)
        if cat.get("seed_queries"):
            seed_names = [q.replace("repo:", "", 1) for q in cat["seed_queries"]]
            for fn in seed_names:
                try:
                    item, hdrs = github_client.get_repo_direct(fn)
                    if hdrs.get("X-RateLimit-Remaining"):
                        rate_remaining = int(hdrs["X-RateLimit-Remaining"])
                    if item:
                        merged[item["full_name"]] = item
                except Exception as e:
                    print(f"    [fetch] FAIL seed {fn}: {e}", file=sys.stderr)
                github_client.sleep_between(auth)

        ranked = sorted(
            merged.values(),
            key=lambda i: i.get("stargazers_count", 0),
            reverse=True,
        )[: cat["top_n"]]

        processed = []
        for item in ranked:
            repo = extract_repo(item)
            repo["category"] = cat["id"]
            apply_deltas(repo, yesterday_stars, weekly_baseline, weekly_window_days)
            processed.append(repo)
            all_repos[repo["full_name"]] = repo

        categories_result.append({
            "category": cat["id"],
            "title": cat["title"],
            "subtitle": cat["subtitle"],
            "queries": cat["queries"] + cat.get("seed_queries", []),
            "total_count": len(processed),
            "items": processed,
        })
        print(f"  -> [{cat['id']}] merged={len(merged)} kept_top={len(processed)}")

        if limit and len(all_repos) >= limit:
            print(f"[fetch] hit --limit {limit}, stopping early")
            break

    repos = list(all_repos.values())

    # v2.1: 对接本地 pending_needs 双向生长回路
    needs = load_pending_needs(needs_file)
    if needs:
        match_pending_needs(repos, needs)
        matched_repos = sum(1 for r in repos if r.get("matched_needs"))
        print(f"[needs] {len(needs)} pending needs | {matched_repos} repos matched")

    total_new = sum(1 for r in repos if r["is_new_this_week"])
    total_action = sum(1 for r in repos if r.get("action_candidate"))
    digest = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_repos": len(repos),
        "total_new": total_new,
        "total_action_candidate": total_action,
        "categories": categories_result,
        "repos": repos,
        "needs": needs,
        "meta": {
            "rate_limit_remaining": rate_remaining,
            "weekly_window_days": weekly_window_days,
            "snapshot_count": snapshot_count,
            "coldstart": snapshot_count == 0,
            "query_mode": "wvb-radar-v0.6-generalized-v2.1",
        },
    }
    print(
        f"[fetch] done: {len(repos)} repos, {total_new} new, "
        f"{total_action} action_candidates, rate_remaining={rate_remaining}"
    )
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="每日开源项目采集 (wvb-radar 模型改造)")
    parser.add_argument("--limit", type=int, default=None, help="最多采集仓库数 (调试用)")
    parser.add_argument("--dry-run", action="store_true", help="只采集不落盘")
    parser.add_argument("--out", type=str, default=None, help="输出文件路径 (默认 data/snapshots/YYYY-MM-DD.json)")
    parser.add_argument("--needs-file", type=str, default=None, help="pending_needs JSON 路径 (默认 data/needs.json)")
    args = parser.parse_args()

    digest = fetch(limit=args.limit, dry_run=args.dry_run, needs_file=args.needs_file)

    if args.dry_run:
        print(json.dumps({"total_repos": digest["total_repos"], "total_new": digest["total_new"]}))
        return 0

    out = Path(args.out) if args.out else SNAPSHOT_DIR / f"{digest['date']}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    print(f"[fetch] wrote {out} ({out.stat().st_size} bytes)")

    # 健康检查: 全空或 >half 分类空 → 视为故障 (与 wvb-cc-radar 一致)
    empty_cats = sum(1 for c in digest["categories"] if c["total_count"] == 0)
    broken = digest["total_repos"] == 0 or (
        digest["categories"] and empty_cats > len(digest["categories"]) / 2
    )
    if broken:
        print("[fetch] BROKEN: 0 repos or >half categories empty -- exit 1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
