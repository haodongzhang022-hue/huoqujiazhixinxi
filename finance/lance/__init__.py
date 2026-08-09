"""finance/lance —— LanceDB 统一数据管理层 (渠道/列/参数/任务/日志/数据/挖掘候选 七表统一管理)。

对齐 Issue #6 后续需求:
  "每个末端到数据 也到获取这里数据的脚本, 数据用 lanceDB 数据库,
   脚本需要先管理获取的数据地址 列名, 获取方式, 以及获取脚本...
   获取数据的爬虫应该分为几个部分, 解除耦合的形式:
     - 爬虫通用的部分 (finance/crawler/base.py)
     - 本渠道 列等信息的定义文件, 存储位置等信息 (channels + column_defs + params 表)
     - 相对本内容下的参数/特征记录 (params 表)
   这些用 lanceDB 统一管理"

七张 LanceDB 表 (finance/data/lance/):
  channels            渠道定义   (数据地址/获取方式/获取脚本/存储位置)
  column_defs         本渠道列定义 (渠道列名 -> 标准字段, 类型, 清洗规则)
  params              本渠道参数/特征 (scope: channel/instrument/fetcher/request/storage/schedule/...)
  fetch_tasks         自动获取定时任务 (interval/cron/manual + next_run)
  run_logs            运行日志 (fetch/discovery/daemon/seed)
  data_records        获取到的数据 (标准字段宽表 + raw 原始行, 按 record_id 去重)
  discovery_candidates 渠道挖掘候选 (新渠道发现 -> 评估 -> 转正入库)

模块:
  store      存储核心: 连接/建表/通用 CRUD
  schema     表结构定义 (标准列)
  registry   渠道注册表: 渠道/列/参数 统一读写 + 种子初始化 + 挖掘转正
  tasks      自动获取任务编排
  datastore  数据落库与查询
  logs       运行日志
  discovery  渠道挖掘 (发现/评估/转正)
  cli        命令行入口 (python -m finance.lance.cli / finance.cli lance ...)
"""

from finance.lance.schema import (
    CHANNEL_COLS, COLUMN_DEF_COLS, PARAM_COLS, TASK_COLS,
    LOG_COLS, RECORD_COLS, CANDIDATE_COLS, LANCE_DIR,
)
from finance.lance.store import LanceStore, get_store
from finance.lance.registry import ChannelRegistry
from finance.lance.tasks import TaskManager
from finance.lance.datastore import DataStore
from finance.lance.logs import RunLogger

__all__ = [
    "LANCE_DIR",
    "CHANNEL_COLS", "COLUMN_DEF_COLS", "PARAM_COLS", "TASK_COLS",
    "LOG_COLS", "RECORD_COLS", "CANDIDATE_COLS",
    "LanceStore", "get_store",
    "ChannelRegistry", "TaskManager", "DataStore", "RunLogger",
]
