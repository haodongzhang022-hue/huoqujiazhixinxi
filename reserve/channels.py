"""reserve/channels.py — 渠道分类漏斗 (Channel Funnel)：把数据获取层组织成
「分类 → 渠道 → 子渠道/单渠道叶节点」的多级漏斗，并提供 2 级汇总与统一格式。

背景与动机 (对齐 ISSUE #6 / #7 的对话诉求)：
  「分类下确认渠道明确、能获取到单个渠道的数据、还是得继续下分——
   期望匹配到单渠道，然后存在 2 级汇总，把它们分级整合起来，格式兼容统一，
   方便数据清洗和使用。」

现状问题：
  数据获取层目前的渠道是**扁平**的：每条 item 只有 `category`(一级分类) 与
  `source`(渠道) 两个并列字段，没有把「分类 → 渠道 → 子渠道」组织成**分层漏斗**，
  也就没有「匹配到单渠道叶节点」和「2 级汇总」的能力，更无法统一喂给上层
  （关系分析层 dims）做后续清洗/模型学习。

本模块在**不改动既有 item 结构**的前提下，新增一个**渠道分层视图**：
  L0  分类 / 大类   category   (repos/papers/news/tech/prediction)   ← 汇总层1(分类汇总)
  L1  渠道 / 数据源  source    (cnb/github/arxiv/hackernews/polymarket/rss) ← 汇总层2(渠道汇总)
  L2  子渠道 / 叶节点 subchannel (如 rss 的具体 feed, cnb 的子类别)   ← 单渠道叶节点

每个 item 会被解析出一条**渠道路径** `channel = category.source.subchannel`：
  repos.cnb.<org/project>   /  papers.arxiv.<subcat>  /  news.hackernews.topstories ...

对外提供：
  channel_layers()        渠道分层定义 (漏斗)
  parse_channel()         把分类/渠道/子渠道解析成统一 Channel
  channel_tree(items)     渠道树 (2 级汇总 + 单渠道叶节点, 分级整合视图)
  match_channel(path)     匹配到单渠道叶节点
  aggregate(items, level) 按指定层级做 2 级汇总
  filter_items(items, path) 按渠道路径取数据 (清洗/消费)

用法:
  from reserve.channels import channel_tree, match_channel, aggregate
  tree = channel_tree(items)            # {分类: {渠道: {子渠道: count}}}
  agg  = aggregate(items, level=1)      # 按渠道汇总
  rows = filter_items(items, "papers.arxiv")   # 取某渠道路径下全部数据
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 渠道分类漏斗 (CHANNEL_LAYERS)
#
# 从漏斗口（最粗、最上层）到漏斗底（最细、单渠道叶节点）。
# 每层都是一个「功能域」，有 id / name / order / 来源字段。
# ---------------------------------------------------------------------------
CHANNEL_LAYERS: list[dict] = [
    {"id": "category",   "name": "分类/大类",  "order": 0, "field": "category",
     "label": "分类"},
    {"id": "source",     "name": "渠道/数据源", "order": 1, "field": "source",
     "label": "渠道"},
    {"id": "subchannel", "name": "子渠道/叶节点", "order": 2, "field": "subchannel",
     "label": "子渠道"},
]

# 字段 -> 层级 反向映射
_LAYER_BY_FIELD = {ly["field"]: ly for ly in CHANNEL_LAYERS}
_LAYERS_BY_ORDER = sorted(CHANNEL_LAYERS, key=lambda ly: ly["order"])


def channel_layers() -> list[dict]:
    """返回渠道分类漏斗定义 (按深度升序)。"""
    return [dict(ly) for ly in _LAYERS_BY_ORDER]


def layer_of_field(field: str) -> Optional[dict]:
    """给定字段名, 返回其所属渠道层级。"""
    ly = _LAYER_BY_FIELD.get(field)
    return dict(ly) if ly else None


def channel_depth(field: str) -> int:
    """给定字段名, 返回漏斗深度 (顶层=0)。"""
    ly = _LAYER_BY_FIELD.get(field)
    return ly["order"] if ly else -1


# 已知渠道 id -> 展示名 (便于人类可读; 未知则原样返回)
CHANNEL_NAMES = {
    "cnb": "CNB 开源平台", "github": "GitHub", "arxiv": "arXiv",
    "hackernews": "Hacker News", "polymarket": "Polymarket", "rss": "RSS 订阅",
    "other": "其他",
}
CATEGORY_NAMES = {
    "repos": "开源项目", "papers": "新论文", "news": "热点信息",
    "tech": "科技进展", "prediction": "预测市场", "other": "其他",
}


@dataclass(frozen=True)
class Channel:
    """一个「渠道路径」的统一表示。

    从分类(大类) → 渠道 → 子渠道(单渠道叶节点)，每一级对应 CHANNEL_LAYERS 一层。
    `*` 表示该层未指定(通配/汇总)。
    """

    category: str = "*"
    source: str = "*"
    subchannel: str = "*"

    def __str__(self) -> str:
        return f"{self.category}.{self.source}.{self.subchannel}"

    @property
    def key(self) -> str:
        return str(self)

    @property
    def short(self) -> str:
        """人类可读短名，如 「分类:论文 → 渠道:arXiv」"""
        parts = []
        if self.category != "*":
            parts.append(f"分类:{CATEGORY_NAMES.get(self.category, self.category)}")
        if self.source != "*":
            parts.append(f"渠道:{CHANNEL_NAMES.get(self.source, self.source)}")
        if self.subchannel != "*":
            parts.append(f"子渠道:{self.subchannel}")
        return " → ".join(parts) if parts else "*"

    def to_dict(self) -> dict:
        return {"category": self.category, "source": self.source,
                "subchannel": self.subchannel}

    def active_layers(self) -> list[dict]:
        """返回该渠道**已指定（非通配）**的层级，按漏斗深度升序。"""
        out = []
        for ly in _LAYERS_BY_ORDER:
            val = getattr(self, ly["field"])
            if val and val != "*":
                item = dict(ly)
                item["value"] = val
                out.append(item)
        return out

    def matches(self, other: "Channel") -> bool:
        """是否属于同一条渠道路径（通配符匹配任意值）。"""
        return all(a == "*" or b == "*" or a == b
                   for a, b in zip(self.to_dict().values(), other.to_dict().values()))

    def is_leaf(self) -> bool:
        """是否已匹配到单渠道叶节点 (三层全部指定)。"""
        return all(getattr(self, ly["field"]) not in ("", "*")
                   for ly in _LAYERS_BY_ORDER)


def parse_channel(spec: str | dict | Channel | None,
                  default_category: str = "*",
                  default_source: str = "*") -> Channel:
    """把字符串/字典/Channel 解析为统一的 Channel。

    支持:
      "papers.arxiv"                        -> 分类=论文, 渠道=arxiv (子渠道未指定)
      "papers.arxiv.cs.AI"                  -> 分类=论文, 渠道=arxiv, 子渠道=cs.AI
      "repos.cnb.<org>/<repo>"              -> 分类=开源, 渠道=cnb, 子渠道=仓库
      {"category": "news", "source": "rss"} -> 字典
      若字符串超过 3 段, 从第 3 段起视为子渠道 (用 "." 连接)。
    """
    if isinstance(spec, Channel):
        return spec
    if spec is None or spec == "" or spec == "*":
        return Channel(category=default_category, source=default_source)
    if isinstance(spec, dict):
        return Channel(
            category=str(spec.get("category") or default_category),
            source=str(spec.get("source") or spec.get("channel") or default_source),
            subchannel=str(spec.get("subchannel") or spec.get("sub") or "*"),
        )
    parts = [p.strip() for p in str(spec).split(".")]
    parts = [p for p in parts if p]
    if not parts:
        return Channel(category=default_category, source=default_source)
    # 单段: 若该值匹配已知渠道 id -> 视为 source (渠道), 否则视为 category (分类)
    if len(parts) == 1 and parts[0] in CHANNEL_NAMES and parts[0] != "other":
        return Channel(category=default_category, source=parts[0], subchannel="*")
    category = parts[0] if len(parts) >= 1 else "*"
    source = parts[1] if len(parts) >= 2 else "*"
    subchannel = ".".join(parts[2:]) if len(parts) >= 3 else "*"
    return Channel(category=category, source=source, subchannel=subchannel)


def channel_of_item(item: dict, default_category: str = "other") -> Channel:
    """从一条归一化 item 中解析出它的渠道路径。

    从 item 取:
      category   -> 分类 (item["category"] 或 extra["category"])
      source     -> 渠道 (item["source"] 或 item["adapter"])
      subchannel -> 子渠道 (item["extra"]["subchannel"] / item["subchannel"] /
                    item["extra"]["feed"] / item["extra"]["type"] ...)
    """
    extra = item.get("extra") or {}
    category = item.get("category") or extra.get("category") or default_category
    source = item.get("source") or item.get("adapter") or "*"
    sub = (item.get("subchannel") or extra.get("subchannel")
           or extra.get("feed") or extra.get("type")
           or extra.get("subsection") or "*")
    # 把 source 的 id 形式 (如 github-repos / cnb-projects) 规整为主 id
    source_id = re.split(r"[-\s]", str(source))[0] if source not in ("*", "") else "*"
    return Channel(category=str(category), source=source_id, subchannel=str(sub))


# ---------------------------------------------------------------------------
# 渠道树 / 汇总 / 匹配 / 过滤
# ---------------------------------------------------------------------------

def channel_tree(items: list[dict] | None = None) -> dict:
    """构建渠道树：分类 → 渠道 → 子渠道 → 条目数。

    返回分级整合视图 (2 级汇总 + 单渠道叶节点)：
      {
        "mode": "channels",
        "generated_at": ...,
        "layers": [CHANNEL_LAYERS...],
        "total_items": N,
        "tree": {
          "repos": {
            "_meta": {"label": "开源项目", "count": 12},
            "cnb": {"_meta": {"label": "CNB 开源平台", "count": 8},
                    "orgA/projB": {"_meta": {"count": 2}}}
          }
        }
      }
    """
    from datetime import datetime, timezone
    counts: dict[tuple, int] = defaultdict(int)
    items = items or []
    for it in items:
        ch = channel_of_item(it)
        key = (ch.category, ch.source, ch.subchannel)
        counts[key] += 1

    tree: dict = {}
    for (cat, src, sub), n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        cnode = tree.setdefault(cat, {"_meta": {
            "label": CATEGORY_NAMES.get(cat, cat), "count": 0}})
        cnode["_meta"]["count"] += n
        if src != "*":
            snode = cnode.setdefault(src, {"_meta": {
                "label": CHANNEL_NAMES.get(src, src), "count": 0}})
            snode["_meta"]["count"] += n
            if sub != "*":
                leaf = snode.setdefault(sub, {"_meta": {"count": 0}})
                leaf["_meta"]["count"] += n

    return {
        "mode": "channels",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "layers": channel_layers(),
        "total_items": sum(counts.values()),
        "tree": tree,
    }


def aggregate(items: list[dict] | None = None, level: int = 1) -> list[dict]:
    """按指定层级做 2 级汇总。

    level:
      0 -> 按分类汇总 (最粗)
      1 -> 按渠道汇总 (第 1 级汇总)
      2 -> 按子渠道汇总 (最细)

    返回排序后的 [{level, key, label, count, channel}]。
    """
    field = CHANNEL_LAYERS[level]["field"] if 0 <= level < len(CHANNEL_LAYERS) else "source"
    buckets: dict[str, dict] = {}
    for it in items or []:
        ch = channel_of_item(it)
        val = getattr(ch, field)
        label = (CATEGORY_NAMES if field == "category" else
                 CHANNEL_NAMES if field == "source" else {}).get(val, val)
        if val not in buckets:
            buckets[val] = {"level": level, "layer": _LAYER_BY_FIELD[field]["name"],
                            "key": val, "label": label, "count": 0, "channel": str(ch)}
        buckets[val]["count"] += 1
    return sorted(buckets.values(), key=lambda b: b["count"], reverse=True)


def match_channel(path: str) -> Channel:
    """把用户输入/脚本传入的渠道路径匹配成统一 Channel（单渠道叶节点或汇总）。"""
    ch = parse_channel(path)
    # 补齐缺省: 若只给 source (如 "arxiv"), 推断其所属分类
    if ch.category == "*" and ch.source != "*":
        guess = _guess_category_by_source(ch.source)
        if guess:
            ch = Channel(category=guess, source=ch.source, subchannel=ch.subchannel)
    return ch


def _guess_category_by_source(source: str) -> Optional[str]:
    return {
        "cnb": "repos", "github": "repos", "arxiv": "papers",
        "hackernews": "news", "polymarket": "prediction", "rss": "tech",
    }.get(source)


def filter_items(items: list[dict], path: str, default_category: str = "other") -> list[dict]:
    """按渠道路径取数据（清洗/消费时最常用）。

    path 支持漏斗任意层级：
      "repos"               -> 取所有开源项目 (分类汇总)
      "papers.arxiv"        -> 取 arXiv 全部 (渠道汇总)
      "papers.arxiv.cs.AI"  -> 取 arXiv 下 cs.AI 子渠道 (单渠道叶节点)

    返回每条 item，并附加解析出的 `channel` 与 `channel_path` 字段。
    """
    target = match_channel(path)
    out = []
    for it in items:
        ch = channel_of_item(it, default_category)
        if target.matches(ch):
            row = dict(it)
            row["channel"] = ch.to_dict()
            row["channel_path"] = str(ch)
            out.append(row)
    return out


def add_channel_field(items: list[dict]) -> list[dict]:
    """为每条 item 统一补上 `channel` 与 `channel_path` 字段 (格式统一)。

    数据清洗/入库前调用，使所有条目都带统一的渠道路径，方便后续按层过滤。
    """
    out = []
    for it in items:
        row = dict(it)
        ch = channel_of_item(it)
        row["channel"] = ch.to_dict()
        row["channel_path"] = str(ch)
        out.append(row)
    return out
