"""pipeline/adapters/cnb.py — CNB 开源平台新项目适配器。

数据来源: CNB OpenAPI `cnb search list-public-repos` (等价 GitHub Trending 的
「平台新项目」信号)。每日聚合管道会把 CNB 上的新项目纳入每日获取,
补足「只盯 GitHub」的盲区。

CLI 依赖: 环境已内置 cnb CLI (登录态保存在 ~/.cnb 或环境凭据)。
实现: 优先调用 cnb CLI (最稳, 走平台认证), 失败时降级 demo 数据 (与
pipeline/data/snapshots/demo-*.json 同样的降级策略, 保证离线可演示)。

配置 (config/sources.json -> sources.cnb):
  {
    "enabled": true,
    "top": 50,               # 拉取条数
    "order_by": "last_updated_at",  # created_at | last_updated_at | stars | forks
    "since_days": 7,         # 只看最近 N 天创建/更新的项目 (默认 7)
    "min_stars": 0           # 最低 star 数过滤
  }
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

from .base import Adapter, AdapterError

# 演示数据 (网络/CLI 不可用时降级, 与 demo 快照策略一致)
_DEMO_ITEMS = [
    {
        "name": "cnb-radar-demo",
        "path": "demo/cnb-radar-demo",
        "description": "CNB 每日新项目雷达 (演示数据): 聚合 CNB 平台新开源项目",
        "web_url": "https://cnb.cool/demo/cnb-radar-demo",
        "star_count": 12, "fork_count": 2, "license": "MIT",
        "topics": "cnb,radar,demo", "created_at": "2026-08-09T00:00:00Z",
        "last_updated_at": "2026-08-09T12:00:00Z",
        "languages": {"language": "Python"},
    },
    {
        "name": "mcp-gateway-demo",
        "path": "demo/mcp-gateway-demo",
        "description": "MCP 网关统一路由演示 (演示数据)",
        "web_url": "https://cnb.cool/demo/mcp-gateway-demo",
        "star_count": 8, "fork_count": 1, "license": "Apache-2.0",
        "topics": "mcp,ai,demo", "created_at": "2026-08-08T00:00:00Z",
        "last_updated_at": "2026-08-09T10:00:00Z",
        "languages": {"language": "Go"},
    },
    {
        "name": "paper-daily-demo",
        "path": "demo/paper-daily-demo",
        "description": "每日论文速递演示: arXiv cs.AI 精选 (演示数据)",
        "web_url": "https://cnb.cool/demo/paper-daily-demo",
        "star_count": 5, "fork_count": 0, "license": "MIT",
        "topics": "paper,arxiv,demo", "created_at": "2026-08-07T00:00:00Z",
        "last_updated_at": "2026-08-09T09:00:00Z",
        "languages": {"language": "Python"},
    },
]


def _parse_date(s: str) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except Exception:
        return s


def _to_item(r: dict) -> dict:
    langs = r.get("languages") or {}
    lang = langs.get("language") if isinstance(langs, dict) else None
    return {
        "item_id": r.get("path") or r.get("id"),
        "title": (r.get("path") or r.get("name") or ""),
        "url": r.get("web_url") or f"https://cnb.cool/{r.get('path', '')}",
        "summary": r.get("description") or "",
        "published_at": _parse_date(r.get("created_at")),
        "updated_at": _parse_date(r.get("last_updated_at")),
        "category": "repos",
        "tags": [t.strip() for t in (r.get("topics") or "").split(",") if t.strip()],
        "score": int(r.get("star_count") or r.get("stars") or 0),
        "extra": {
            "platform": "cnb",
            "forks": r.get("fork_count") or 0,
            "license": r.get("license") or "",
            "language": lang,
            "open_issues": r.get("open_issue_count") or 0,
            "open_prs": r.get("open_pull_request_count") or 0,
            "visibility": r.get("visibility_level") or "",
        },
        "raw": r,
    }


class CNBAdapter(Adapter):
    id = "cnb"
    name = "CNB 开源平台新项目"
    category = "repos"
    description = "通过 cnb search list-public-repos 拉取 CNB 平台新项目 (每日纳入)"

    def fetch(self) -> list[dict]:
        top = int(self.config.get("top", 50))
        order_by = self.config.get("order_by", "last_updated_at")
        since_days = int(self.config.get("since_days", 7))
        min_stars = int(self.config.get("min_stars", 0))

        items = self._fetch_via_cli(top, order_by)
        if not items:
            # CLI 不可用 → demo 降级
            items = [dict(x) for x in _DEMO_ITEMS]
            print(f"[cnb] CLI 不可用, 使用 {len(items)} 条演示数据", flush=True)

        # 时间窗口过滤
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        out = []
        for r in items:
            ts = _parse_date(r.get("created_at"))
            if ts:
                try:
                    if datetime.fromisoformat(ts) < cutoff:
                        continue
                except Exception:
                    pass
            if min_stars and int(r.get("star_count") or 0) < min_stars:
                continue
            out.append(_to_item(r))
        return out

    @staticmethod
    def _fetch_via_cli(top: int, order_by: str) -> list[dict]:
        """调用 cnb search list-public-repos 并解析 JSON 输出。"""
        cmd = ["cnb", "search", "list-public-repos",
               "--topN", str(max(1, min(100, top))),
               "--order-by", order_by, "--desc", "--verbose"]
        env = dict(os.environ)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            print(f"[cnb] cnb CLI 调用失败: {e}", flush=True)
            return []
        if proc.returncode != 0:
            print(f"[cnb] cnb CLI 退出码 {proc.returncode}: {proc.stderr[:300]}", flush=True)
            return []
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            print(f"[cnb] cnb CLI 输出解析失败: {e}", flush=True)
            return []
        return data.get("data") or []


# 注册
from .base import registry  # noqa: E402

registry.register(CNBAdapter)
