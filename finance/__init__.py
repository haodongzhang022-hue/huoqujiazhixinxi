"""finance —— 全球金融数据获取能力的超索引框架 (Data Source Super Index)。

设计目标 (对齐 Issue #6):
  "对全球各个方面金融数据的总框架" —— 一个**管理数据获取能力**的超大索引框架:

    数据类别(股票/期货/外汇/区块链/宏观/舆论/债券/基金/房地产/大宗现货)
        × 国家/地区 × 交易所/市场 × 时间级别 × 品种 × 交易类型(现货/合约/期权/永续…)
        × 获取脚本(每个分类不同的获取方式)
        => 筛选器 -> 索引到目标 -> 渐进式披露(索引/元数据/全量) -> 触发获取 / 定时自动获取

六大核心模块:
  taxonomy    分类体系: 数据类别/国家/交易所/时间级别/交易类型/品种 (config/finance/taxonomy.json)
  catalog     数据源目录: 每个数据源覆盖范围 + 获取脚本 + 调度 + 披露级别 (config/finance/catalog.json)
  filter      筛选器: 按任意维度组合定位品种/数据源
  disclosure  渐进式披露: index -> meta -> full 三级
  scheduler   调度器: 频率/时间/自动获取 (cron / interval / manual)
  registry    获取器注册表: 脚本名 -> 可调用适配器, 触发获取

目录结构:
  config/finance/taxonomy.json   六维分类体系
  config/finance/catalog.json    数据源注册目录
  finance/fetchers/              每个分类的获取脚本 (适配器骨架 + 可扩展)
  finance/data/cache/            获取数据的落地缓存

快速开始:
  python -m finance.cli search --data-class stock --region CN
  python -m finance.cli index --instrument CN.RB
  python -m finance.cli fetch --instrument CN.RB --time-level 1d --source akshare
  python -m finance.cli schedule --instrument CRYPTO.BTC --every 5m
  python -m finance.api --port 8100
"""

__version__ = "0.1.0"

from finance.taxonomy import Taxonomy, load_taxonomy, TAXONOMY_PATH
from finance.catalog import Catalog, load_catalog, CATALOG_PATH

__all__ = [
    "Taxonomy", "load_taxonomy", "TAXONOMY_PATH",
    "Catalog", "load_catalog", "CATALOG_PATH",
    "__version__",
]
