"""pipeline/adapters/polymarket.py — 预测市场适配器 (Polymarket Gamma API)。

背景 (ISSUE #5): 预测市场 (如 Polymarket / Kalshi) 里的事件概率、成交量、
多空走向, 是「预测某事物是否发生和走向」的重要信号。本适配器把
Polymarket 活跃事件 (active=true, closed=false) 拉取为统一 item,
供每日聚合与后续「预测/对冲风险」专项开发复用。

数据来源: https://gamma-api.polymarket.com/events (公开 API, 无需 key)
  - 事件含: question / outcomePrices / volume / liquidity / startDate / endDate
  - 概率 = outcomePrices 的 YES 价格 (0~1)

⚠️ 注意: 预测市场数据是**结构化行情**, 不是文章; 页面上以「预测事件卡片」
展示 (标题 + YES 概率 + 成交量 + 截止时间), 单独对接成数据信息需要后续专项开发
(见 docs/sources-extension.md §6)。

配置 (config/sources.json -> sources.polymarket):
  {
    "enabled": true,
    "limit": 10,
    "active": true, "closed": false, "archived": false,
    "order": "volume24hr"
  }
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import Adapter, AdapterError

PM_API = "https://gamma-api.polymarket.com/events"


class PolymarketAdapter(Adapter):
    id = "polymarket"
    name = "预测市场 (Polymarket)"
    category = "prediction"
    description = "Polymarket 活跃事件: 概率/成交量/走向信号"

    def fetch(self) -> list[dict]:
        limit = int(self.config.get("limit", 10))
        params = {
            "limit": limit,
            "active": str(self.config.get("active", True)).lower(),
            "closed": str(self.config.get("closed", False)).lower(),
            "archived": str(self.config.get("archived", False)).lower(),
            "order": self.config.get("order", "volume24hr"),
            "ascending": "false",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        try:
            data = self.http_json(f"{PM_API}?{qs}", timeout=25)
        except AdapterError:
            print("[polymarket] 网络不可用, 使用演示数据", flush=True)
            return self._demo()
        if not isinstance(data, list):
            raise AdapterError("polymarket: 响应异常")
        items = []
        for ev in data:
            markets = ev.get("markets") or []
            if not markets:
                continue
            m = markets[0]
            yes_price = _yes_price(m)
            items.append({
                "item_id": str(ev.get("id") or m.get("id")),
                "title": ev.get("question") or m.get("question") or ev.get("title") or "(预测事件)",
                "url": ev.get("slug") and f"https://polymarket.com/event/{ev['slug']}" or "",
                "summary": "",
                "published_at": ev.get("startDate") or ev.get("createdAt"),
                "category": "prediction",
                "tags": ["polymarket", "prediction"],
                "score": float(ev.get("volume") or m.get("volume") or 0),
                "extra": {
                    "platform": "polymarket",
                    "probability_yes": yes_price,
                    "volume": ev.get("volume") or m.get("volume") or 0,
                    "volume24hr": ev.get("volume24hr") or 0,
                    "liquidity": ev.get("liquidity") or m.get("liquidity") or 0,
                    "end_date": ev.get("endDate") or m.get("endDate") or "",
                    "outcome_prices": m.get("outcomePrices") or "",
                    "category": ev.get("category") or "",
                },
                "raw": ev,
            })
        return items

    @staticmethod
    def _demo() -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "item_id": "demo-pm-1",
                "title": "[演示] 2026 年底前 AGI 是否出现 (示例预测事件)",
                "url": "https://polymarket.com/event/demo-agi",
                "summary": "", "published_at": now,
                "category": "prediction", "tags": ["polymarket", "demo"], "score": 1200000,
                "extra": {"platform": "polymarket", "probability_yes": 0.12,
                          "volume": 1200000, "volume24hr": 35000, "liquidity": 80000,
                          "end_date": "2026-12-31T00:00:00Z"},
            },
            {
                "item_id": "demo-pm-2",
                "title": "[演示] 某大厂 Q4 是否发布自研芯片 (示例预测事件)",
                "url": "https://polymarket.com/event/demo-chip",
                "summary": "", "published_at": now,
                "category": "prediction", "tags": ["polymarket", "demo"], "score": 860000,
                "extra": {"platform": "polymarket", "probability_yes": 0.43,
                          "volume": 860000, "volume24hr": 21000, "liquidity": 50000,
                          "end_date": "2026-12-31T00:00:00Z"},
            },
            {
                "item_id": "demo-pm-3",
                "title": "[演示] 某开源模型是否登顶 LLM 榜单 (示例预测事件)",
                "url": "https://polymarket.com/event/demo-llm",
                "summary": "", "published_at": now,
                "category": "prediction", "tags": ["polymarket", "demo"], "score": 540000,
                "extra": {"platform": "polymarket", "probability_yes": 0.67,
                          "volume": 540000, "volume24hr": 12000, "liquidity": 30000,
                          "end_date": "2026-12-31T00:00:00Z"},
            },
        ]


def _yes_price(m: dict) -> float | None:
    """解析 outcomePrices "0.43,0.57" -> YES 概率 (第一项)。"""
    s = m.get("outcomePrices") or ""
    if not s:
        return None
    try:
        first = s.split(",")[0].strip()
        return round(float(first), 4)
    except (ValueError, IndexError):
        return None


# 注册
from .base import registry  # noqa: E402

registry.register(PolymarketAdapter)
