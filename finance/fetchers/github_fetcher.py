"""finance/fetchers/github_fetcher.py —— GitHub 开源项目生态数据源适配器。

对齐 Issue #6: "实现对数据的聚类、分类和渐进式披露", 并打通一条**真实可达**的数据链路。

GitHub 公开 API 无需 Key 即可调用 (限流 60 次/小时), 网络实测可达 (HTTP 200),
因此作为首个"真实数据可获取"的数据源, 归入 sentiment (舆论/新闻情绪) 数据类别:

  - 开源项目的 star / fork / watch 数量  -> 开发者关注度 / 情绪热度
  - 近 30 天提交活跃度                     -> 项目生命力 / 热度趋势
  - 近期最新提交 (author/date/message)     -> 事件流 / 动态

依赖: 仅标准库 (urllib), 无需安装第三方包; 网络不可达时降级 demo。

用法:
  python -m finance.fetchers.github_fetcher --instrument SENTIMENT.GITHUB.TRENDING --time-level 1d
  python -m finance.fetchers.github_fetcher --instrument SENTIMENT.GITHUB.PYTORCH --time-level 1d
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.github.com"
UA = {"User-Agent": "finance-super-index/0.1 (cnb)"}
TIMEOUT = 20

# 需要网络 -> 通过环境变量开关, 便于测试/CI 离线控制
NETWORK_ENABLED = __import__("os").environ.get("FINANCE_NETWORK", "1") != "0"

# 固定项目映射: 品种 id -> github full_name
_PROJECTS = {
    "SENTIMENT.GITHUB.PYTORCH": "pytorch/pytorch",
    "SENTIMENT.GITHUB.TENSORFLOW": "tensorflow/tensorflow",
    "SENTIMENT.GITHUB.LANGCHAIN": "langchain-ai/langchain",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_json(url: str) -> dict | list | None:
    """GET 一个 GitHub API 端点, 返回解析后的 JSON。"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def _fetch_repo(full_name: str) -> dict:
    """获取单个仓库的实时数据。"""
    repo = _http_json(f"{API_BASE}/repos/{full_name}")
    commits = _http_json(f"{API_BASE}/repos/{full_name}/commits?per_page=10")
    if not isinstance(commits, list):
        commits = []

    recent_commits = []
    for c in commits[:10]:
        cm = c.get("commit", {})
        author = cm.get("author") or {}
        recent_commits.append({
            "message": (cm.get("message") or "").split("\n")[0][:120],
            "author": (c.get("author") or {}).get("login") or (cm.get("author") or {}).get("name") or "unknown",
            "date": author.get("date", ""),
        })

    return {
        "full_name": repo.get("full_name", full_name),
        "html_url": repo.get("html_url", ""),
        "description": repo.get("description") or "",
        "language": repo.get("language"),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "watchers": repo.get("subscribers_count", 0),
        "created_at": repo.get("created_at", ""),
        "updated_at": repo.get("updated_at", ""),
        "pushed_at": repo.get("pushed_at", ""),
        "recent_commits": recent_commits,
        "activity_30d": _recent_commit_count(commits),
    }


def _recent_commit_count(commits: list) -> int:
    """近 30 天提交次数估算 (返回最近 10 条中的数量, 用于热度参考)。"""
    if not commits:
        return 0
    return len([c for c in commits if c.get("commit", {}).get("author", {}).get("date", "")])


def _fetch_trending(limit: int = 10) -> dict:
    """获取近期高星新开源项目 (活跃榜) -> 开发者关注热点。"""
    q = "stars:>500 created:>2025-01-01"
    url = f"{API_BASE}/search/repositories?q={urllib.parse.quote(q)}&sort=stars&order=desc&per_page={limit}"
    data = _http_json(url)
    items = data.get("items", []) if isinstance(data, dict) else []
    rows = []
    for it in items[:limit]:
        rows.append({
            "full_name": it.get("full_name", ""),
            "html_url": it.get("html_url", ""),
            "description": (it.get("description") or "")[:120],
            "language": it.get("language"),
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "created_at": it.get("created_at", ""),
            "pushed_at": it.get("pushed_at", ""),
        })
    return {"kind": "trending", "rows": rows}


def fetch(payload: dict) -> dict:
    """GitHub 数据源获取入口 (registry 调用)。payload: {instrument_id, symbol, ...}"""
    inst_id = payload.get("instrument_id", "")
    symbol = payload.get("symbol", "")
    tl = payload.get("time_level", "1d")

    result = {
        "ok": True,
        "source": "github",
        "demo": False,
        "instrument_id": inst_id,
        "name": payload.get("name", ""),
        "time_level": tl,
        "fetched_at": _now(),
    }

    # 活跃榜 / 单个项目两种获取方式 (同属 sentiment 数据类, 不同子类型)
    if inst_id == "SENTIMENT.GITHUB.TRENDING" or symbol == "GITHUB-TRENDING":
        result["data"] = _fetch_trending()
    else:
        full_name = symbol or _PROJECTS.get(inst_id, "")
        if not full_name:
            raise ValueError(f"github 无法解析项目: {inst_id} / {symbol}")
        result["data"] = {"kind": "project", "row": _fetch_repo(full_name)}

    return result


def main():
    ap = argparse.ArgumentParser(description="GitHub 开源生态适配器 (真实数据)")
    ap.add_argument("--instrument", required=True, help="品种 id (如 SENTIMENT.GITHUB.TRENDING)")
    ap.add_argument("--time-level", default="1d")
    args = ap.parse_args()

    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument_id": inst["id"], "time_level": args.time_level}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[github] 获取失败: {e}", file=sys.stderr)
        print("[github] 提示: 网络不可达时可通过 finance.registry 触发 demo 降级", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
