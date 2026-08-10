"""pipeline/adapters — 多源信息适配器框架。

设计目标 (ISSUE #5):
  站点/获取方式会持续增加 (CNB 项目 / 其他开源站点 / 论文 / 热点 / 科技进展 /
  预测市场 ...), 每个新来源只需实现一个 Adapter, 注册到 config/sources.json
  即可被每日聚合管道与 Web「每日聚合」页签自动纳入, 无需改主流程。

内置适配器:
  cnb          CNB 开源平台新项目 (cnb search list-public-repos)
  github       已有 GitHub 采集 (包装 pipeline.fetch 的每日快照)
  arxiv        arXiv 论文预印本 (cs.AI / cs.CL / cs.LG / cs.SE ...)
  hackernews   Hacker News 热点 (topstories + item 详情)
  polymarket   预测市场 (Polymarket Gamma API: 事件/市场/成交量/价格)
  rss          通用 RSS/Atom 聚合 (科技进展 / 站点更新 / 博客)

用法:
  from pipeline.adapters import registry, fetch_all
  registry.list_adapters()          # 查看可用适配器
  fetch_all(only=["cnb", "arxiv"])  # 拉取并写缓存 pipeline/data/sources/*.json
"""

from __future__ import annotations

from .base import Adapter, AdapterError, normalize_item, registry, fetch_all, fetch_one  # noqa: F401

# 导入内置适配器以完成注册 (按依赖轻→重排序)
from . import cnb as _cnb  # noqa: F401,E402
from . import github as _github  # noqa: F401,E402
from . import arxiv as _arxiv  # noqa: F401,E402
from . import hackernews as _hn  # noqa: F401,E402
from . import polymarket as _pm  # noqa: F401,E402
from . import rss as _rss  # noqa: F401,E402

__all__ = ["Adapter", "AdapterError", "normalize_item", "registry", "fetch_all", "fetch_one"]
