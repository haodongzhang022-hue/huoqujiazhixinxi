"""finance/lance/schema.py —— LanceDB 七张表的列结构定义 (标准列)。

设计原则:
  - LanceDB 表先写入即定型 schema, 为便于演进, 所有表都带 `ext` (JSON 扩展字段)
    与 `ts` (UTC 时间戳), 新增字段优先进 ext, 避免频繁改表。
  - 所有 id 使用 `渠道id:品种id[:时间级别[:交易类型]]` 复合结构, 天然支持
    "数据地址 -> 列名 -> 获取方式 -> 获取脚本" 的末端索引。
"""

from __future__ import annotations

from pathlib import Path

# LanceDB 数据目录 (仓库内运行时生成, .gitignore 已忽略)
LANCE_DIR = Path(__file__).resolve().parent.parent.parent / "finance" / "data" / "lance"

# 数据库目录别名 (用户可覆盖)
FINANCE_LANCE_DIR = "finance/data/lance"

# ---------------- 各表标准列 (与 finance/data/lance/SCHEMA.md 保持一致) ----------------

# channels 渠道定义表
CHANNEL_COLS = [
    "channel_id",       # 渠道 id (数据源 id, 如 akshare / ccxt / cnb-sitemap)
    "name",             # 渠道名称
    "name_en",          # 英文名
    "kind",             # 渠道种类: python_lib / http_api / rss / website / csv / manual / ...
    "data_classes",     # 覆盖数据类别 [stock, futures, ...]
    "regions",          # 覆盖国家/地区 [CN, US, ...]
    "exchanges",        # 覆盖交易所 [SSE, SHFE, ...]
    "status",           # active / disabled / candidate / deprecated
    "source",           # 数据地址 (API 端点/站点 URL/文件路径/库名)
    "method",           # 获取方式 (http_get / python_lib / rss_parse / file_read / manual ...)
    "script",           # 获取脚本路径 (相对仓库根)
    "module",           # 可导入模块 (finance.crawler.fetchers.xxx 或 finance.fetchers.xxx)
    "command",          # 命令行示例
    "auth",             # 认证说明 (JSON 字符串, 不存密钥本身)
    "rate_limit",       # 限流说明
    "storage",          # 存储配置 (JSON: 落库位置/文件路径)
    "schedule",         # 默认调度 (JSON: default_frequency/default_cron)
    "disclosure",       # 披露级别 (JSON)
    "requires",         # 依赖 (JSON: pip 包列表)
    "fetchers",         # 子获取器 (JSON 列表)
    "params",           # 渠道级默认参数 (JSON, 冗余便于索引)
    "enabled",          # 是否启用 (bool)
    "discovered_from",  # 挖掘来源 (candidate id / manual / 初始化)
    "last_run_at",      # 最近一次运行时间
    "last_status",      # 最近一次状态 (ok/failed/...)
    "created_at",       # 创建时间
    "updated_at",       # 更新时间
    "ext",              # 扩展 JSON
    "ts",               # 时间戳
]

# column_defs 列定义表 (渠道列 -> 标准字段)
COLUMN_DEF_COLS = [
    "channel_id",       # 所属渠道
    "source_col",       # 渠道原始列名 (如 '日期' / 'close' / 'price')
    "standard_col",     # 映射到的标准字段 (如 ts / open / high / low / close / volume / title ...)
    "col_type",         # 列类型 (string / float / int / datetime / bool / json)
    "description",      # 列含义
    "cleaning",         # 清洗/转换规则 (JSON: 如 {"trim": true, "parse_date": "%Y-%m-%d"})
    "required",         # 是否必填 (bool)
    "enabled",          # 是否启用 (bool)
    "params",           # 本列扩展参数 (JSON)
    "created_at",
    "updated_at",
    "ext",
    "ts",
]

# params 参数表 (渠道/品种/获取器/请求/存储/调度 各级参数与特征)
PARAM_COLS = [
    "param_id",         # 参数 id: {channel_id}:{scope}:{key}
    "channel_id",       # 所属渠道
    "scope",            # 作用域: channel / instrument / fetcher / request / storage / schedule / feature
    "key",              # 参数键
    "value",            # 参数值 (JSON 序列化)
    "value_type",       # string / number / bool / json / list
    "description",      # 参数说明
    "instrument_id",    # 品种 id (scope=instrument 时)
    "created_at",
    "updated_at",
    "ext",
    "ts",
]

# fetch_tasks 自动获取定时任务表
TASK_COLS = [
    "task_id",          # 任务 id (uuid)
    "name",             # 任务名
    "channel_id",       # 渠道
    "instrument_id",    # 品种
    "time_level",       # 时间级别
    "trade_type",       # 交易类型
    "task_type",        # interval / cron / manual / once
    "every",            # 间隔描述 (如 5m / 1h / 1d)
    "cron",             # cron 表达式
    "at",               # 每日时刻 HH:MM
    "enabled",          # 是否启用
    "params",           # 任务参数 (JSON)
    "next_run_at",      # 下次运行时间
    "last_run_at",      # 上次运行时间
    "last_status",      # ok / failed / skipped
    "last_error",       # 上次错误
    "run_count",        # 累计运行次数
    "created_at",
    "updated_at",
    "ext",
    "ts",
]

# run_logs 运行日志表
LOG_COLS = [
    "log_id",           # 日志 id (uuid)
    "run_type",         # fetch / discovery / daemon / seed / test
    "channel_id",       # 渠道 (可为空)
    "instrument_id",    # 品种 (可为空)
    "task_id",          # 任务 (可为空)
    "status",           # ok / failed / partial / skipped
    "message",          # 日志消息
    "rows_count",       # 处理行数
    "duration_ms",      # 耗时毫秒
    "detail",           # 详情 JSON
    "created_at",
    "ts",
]

# data_records 数据表 (标准字段宽表)
RECORD_COLS = [
    "record_id",        # {channel_id}:{instrument_id}:{time_level or date}:{trade_type or ''}[:hash]
    "channel_id",       # 渠道
    "instrument_id",    # 品种
    "instrument_name",  # 品种名
    "data_class",       # 数据类别
    "region",           # 国家/地区
    "exchange",         # 交易所
    "time_level",       # 时间级别
    "trade_type",       # 交易类型
    "ts",               # 时间戳 (记录的时间点)
    "open",             # 标准字段: 开
    "high",             # 标准字段: 高
    "low",              # 标准字段: 低
    "close",            # 标准字段: 收
    "volume",           # 标准字段: 量
    "amount",           # 标准字段: 额
    "title",            # 标准字段: 标题 (新闻/舆论)
    "link",             # 标准字段: 链接
    "content",          # 标准字段: 正文/摘要
    "value",            # 标准字段: 通用数值 (宏观/指数)
    "raw",              # 原始行 JSON (渠道原始列名)
    "extra",            # 扩展 JSON
    "source_meta",      # 获取元信息 (JSON: script/version/url)
    "created_at",       # 入库时间
]

# discovery_candidates 渠道挖掘候选表
CANDIDATE_COLS = [
    "candidate_id",     # 候选 id
    "name",             # 候选渠道名
    "url",              # 发现地址
    "discovery_source", # 挖掘来源 (engine/seed/website/manual/...)
    "kind",             # 候选种类 (http_api / website / rss / python_lib ...)
    "data_classes",     # 可能的数据类别
    "regions",          # 可能的地区
    "notes",            # 备注 (为何有价值)
    "status",           # new / evaluating / approved / rejected / promoted
    "score",            # 评估分数 (0-100)
    "probe_result",     # 探测结果 (JSON)
    "promoted_channel_id",  # 转正后的渠道 id
    "created_at",
    "updated_at",
    "ext",
    "ts",
]

# 表名常量
TABLES = {
    "channels": CHANNEL_COLS,
    "column_defs": COLUMN_DEF_COLS,
    "params": PARAM_COLS,
    "fetch_tasks": TASK_COLS,
    "run_logs": LOG_COLS,
    "data_records": RECORD_COLS,
    "discovery_candidates": CANDIDATE_COLS,
}
