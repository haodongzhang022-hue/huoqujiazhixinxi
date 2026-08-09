"""pipeline/adapters/hackernews.py — Hacker News 热点适配器。

数据来源: Hacker News Firebase API (firebaseio.com, 无需 key)。
拉取 topstories 前 N 条 + item 详情, 得到当日科技热点 (标题/链接/分数/评论数)。

配置 (config/sources.json -> sources.hackernews):
  {
    "enabled": true,
    "top": 20,
    "min_score": 50
  }
"""

from __future__ import annotations

import time

from .base import Adapter, AdapterError

HN_API = "https://hacker-news.firebaseio.com/v0"


class HackerNewsAdapter(Adapter):
    id = "hackernews"
    name = "Hacker News 热点"
    category = "news"
    description = "HN topstories 当日科技热点 (标题/链接/分数/评论)"

    def fetch(self) -> list[dict]:
        top = int(self.config.get("top", 20))
        min_score = int(self.config.get("min_score", 0))
        try:
            ids = self.http_json(f"{HN_API}/topstories.json", timeout=20)
        except AdapterError:
            # 网络不可用 → 演示数据 (与 demo 策略一致)
            print("[hackernews] 网络不可用, 使用演示数据", flush=True)
            return self._demo()
        if not isinstance(ids, list):
            raise AdapterError("hackernews: topstories 响应异常")
        items = []
        for iid in ids[:top]:
            item = self.http_json(f"{HN_API}/item/{iid}.json", timeout=15)
            if not item or item.get("type") != "story":
                continue
            score = int(item.get("score") or 0)
            if score < min_score:
                continue
            items.append({
                "item_id": str(item.get("id")),
                "title": item.get("title") or "",
                "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}",
                "summary": "",
                "published_at": _ts(item.get("time")),
                "category": "news",
                "tags": ["hackernews", "hot"],
                "score": score,
                "extra": {
                    "platform": "hackernews",
                    "comments": int(item.get("descendants") or 0),
                    "by": item.get("by") or "",
                },
                "raw": item,
            })
            time.sleep(0.1)
        return items

    @staticmethod
    def _demo() -> list[dict]:
        return [
            {
                "item_id": "demo-hn-1", "title": "[演示] LLM Agent 每日信息聚合实践",
                "url": "https://news.ycombinator.com/item?id=demo1",
                "summary": "", "published_at": "2026-08-09T08:00:00Z",
                "category": "news", "tags": ["hackernews", "demo"], "score": 320,
                "extra": {"platform": "hackernews", "comments": 45},
            },
            {
                "item_id": "demo-hn-2", "title": "[演示] 开源 MCP 网关发布",
                "url": "https://news.ycombinator.com/item?id=demo2",
                "summary": "", "published_at": "2026-08-09T07:30:00Z",
                "category": "news", "tags": ["hackernews", "demo"], "score": 210,
                "extra": {"platform": "hackernews", "comments": 30},
            },
            {
                "item_id": "demo-hn-3", "title": "[演示] 本地向量数据库性能对比",
                "url": "https://news.ycombinator.com/item?id=demo3",
                "summary": "", "published_at": "2026-08-09T07:00:00Z",
                "category": "news", "tags": ["hackernews", "demo"], "score": 150,
                "extra": {"platform": "hackernews", "comments": 22},
            },
        ]


def _ts(t) -> str:
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).isoformat()
    except Exception:
        return ""


# 注册
from .base import registry  # noqa: E402

registry.register(HackerNewsAdapter)
