"""pipeline/adapters/github.py — GitHub 开源项目适配器。

包装现有 pipeline/fetch.py 的每日快照 (data/snapshots/YYYY-MM-DD.json),
把 GitHub 采集结果归一化为统一 item 结构, 与 cnb/arxiv 等源在同一张
「每日聚合」时间线里展示。本身不重复调用 GitHub API (避免配额翻倍)。

配置 (config/sources.json -> sources.github):
  {
    "enabled": true,
    "days": 3,          # 回看最近 N 天快照
    "min_stars": 0,
    "only_decision": "" # action|reserve|partial 过滤
  }
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .base import Adapter, AdapterError

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "pipeline" / "data" / "snapshots"


class GitHubAdapter(Adapter):
    id = "github"
    name = "GitHub 开源项目 (每日快照)"
    category = "repos"
    description = "包装 pipeline.fetch 的每日快照, 纳入统一每日聚合"

    def fetch(self) -> list[dict]:
        days = int(self.config.get("days", 3))
        min_stars = int(self.config.get("min_stars", 0))
        only_decision = self.config.get("only_decision", "")

        snaps = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
        if not snaps:
            raise AdapterError("github: 暂无每日快照, 先运行 python -m pipeline.fetch")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items: list[dict] = []
        for p in snaps:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            repos = raw.get("repos") or raw.get("items") or []
            for r in repos:
                stars = int(r.get("stars") or r.get("stargazers_count") or 0)
                if stars < min_stars:
                    continue
                if only_decision and r.get("category_decision") != only_decision:
                    continue
                items.append({
                    "item_id": r.get("repo_id") or r.get("full_name"),
                    "title": r.get("full_name") or r.get("name"),
                    "url": r.get("url") or r.get("html_url") or "",
                    "summary": r.get("description") or r.get("function_summary") or "",
                    "published_at": r.get("first_seen_at") or r.get("created_at") or p.stem,
                    "category": "repos",
                    "tags": (r.get("function_tags") or []) + (r.get("topics") or [])[:5],
                    "score": stars,
                    "extra": {
                        "platform": "github",
                        "stars": stars,
                        "stars_delta_24h": r.get("stars_delta_24h") or 0,
                        "stars_delta_7d": r.get("stars_delta_7d") or 0,
                        "language": r.get("language") or "",
                        "is_new_this_week": bool(r.get("is_new_this_week")),
                        "category_decision": r.get("category_decision") or "",
                        "category": r.get("category") or "",
                    },
                    "raw": r,
                })
        return items


# 注册
from .base import registry  # noqa: E402

registry.register(GitHubAdapter)
