# LanceDB 统一数据管理层 (Finance LanceDB Layer)

> 对齐 Issue #6 后续需求：**数据用 LanceDB 数据库**，脚本统一管理「数据地址 / 列名 / 获取方式 / 获取脚本」，并将爬虫**解耦**为「通用模板 + 分渠道定义文件」。

## 一、设计理念：解除耦合

获取数据的爬虫分为三个部分（各自独立，互不耦合）：

| 部分 | 位置 | 说明 |
|---|---|---|
| **1. 爬虫通用部分**（通用模板） | `finance/crawler/` | 请求/重试/限流/解析/分页、标准字段映射、渠道调度分发，与具体渠道无关 |
| **2. 渠道定义文件** | LanceDB `channels` 表 | 每个渠道的数据地址(source)、获取方式(method)、获取脚本(script/module)、存储位置(storage) |
| **3. 本渠道参数/特征记录** | LanceDB `params` + `column_defs` 表 | 渠道级/品种级/获取器级/请求级参数；渠道原始列名 -> 标准字段映射与清洗规则 |

**新渠道 = 在 LanceDB 登记 3 类记录（channels + column_defs + params）+ 可选自定义 fetcher 模块**，通用引擎自动完成「获取 → 映射 → 清洗 → 落库」全链路，无需改动通用代码。

## 二、七张 LanceDB 表

数据目录：`finance/data/lance/`（运行时生成，已 gitignore）

| 表 | 用途 | 主键 | 关键列 |
|---|---|---|---|
| `channels` | 渠道定义（数据地址/获取方式/脚本/存储） | channel_id | source, method, script, module, storage, schedule, status |
| `column_defs` | 本渠道列定义（原始列 -> 标准字段） | (channel_id, source_col) | standard_col, col_type, cleaning |
| `params` | 渠道/品种/获取器/请求/存储/调度参数 | param_id | scope, key, value, instrument_id |
| `fetch_tasks` | 自动获取定时任务 | task_id | channel_id, instrument_id, every/at/cron, next_run_at |
| `run_logs` | 运行日志 | log_id | run_type, status, rows_count, message |
| `data_records` | 获取到的数据（标准字段宽表 + raw） | record_id | ts, open/high/low/close/volume, title/link/content, value, raw |
| `discovery_candidates` | 渠道挖掘候选 | candidate_id | url, status(new/evaluated/promoted), score, probe_result |

## 三、两个定时爬虫

### 1. 自动获取数据定时爬虫 (`fetch_tasks` + `TaskManager`)

```
python -m finance.cli lance tasks --add --channel akshare --instrument CN.RB --every 1d   # 每日
python -m finance.cli lance tasks --add --channel ccxt --instrument CRYPTO.BTC --every 5m # 每5分钟
python -m finance.cli lance tasks --add --channel rss_news --every 1h                     # 每小时
python -m finance.cli lance tasks --run-due   # 扫描到期任务并执行 (供 cron/CI 周期调用)
python -m finance.cli lance tasks --run-all   # 立即执行所有任务
```

- 调度类型：`interval`(每 N 秒/分/时/天) / `daily-at`(每天 HH:MM) / `cron`
- 任务状态持久化在 LanceDB，重启不丢；`next_run_at` 自动推进

### 2. 挖掘新渠道的定时爬虫 (`discovery_candidates` + `ChannelDiscovery`)

```
python -m finance.cli lance discovery --discover   # 发现候选渠道
python -m finance.cli lance discovery --evaluate   # 探测可达性/内容类型并打分(0-100)
python -m finance.cli lance discovery --promote <candidate_id> --channel-id <新渠道id>  # 转正
python -m finance.cli lance discovery --run        # 一键: 发现+评估+转正(可选)
```

- 挖掘引擎：`cnb_platform`(CNB 平台公开仓库/组织)、`seed_expansion`(从现有渠道 coverage 反查未覆盖地区)、`awesome_github`(可扩展)
- 评估：HTTP 可达性、HTML/RSS/JSON 内容识别、金融关键词、表格检测 → 综合评分
- 转正：候选 → 自动写入 channels + column_defs + params 三表（默认不自动启用，待人工确认列定义）
- `discovery --run` 会自动注册一个 `discovery` 渠道的每日定时任务，持续挖掘新渠道

## 四、数据链路（端到端）

```
taxonomy/catalog (六维索引框架)
   ↓ 筛选器定位品种
索引到渠道 (channels 表: 数据地址/获取方式/获取脚本/存储位置)
   ↓ 通用引擎 (crawler/base.py) 或 分渠道 fetcher (crawler/fetchers/)
原始行 (渠道列名)
   ↓ 字段映射 (column_defs 表 + crawler/fields.py)
标准行 (ts/open/high/low/close/volume/title/link/content/value + raw)
   ↓ 落库 (data_records 表, record_id 去重)
LanceDB 统一数据 → 查询/统计/渐进式披露/喂给上层分析
```

## 五、快速开始

```bash
# 1. 初始化 (建表 + 从 catalog 迁移现有 8 数据源/28 品种)
python -m finance.cli lance init

# 2. 触发一次渠道获取 (无真实依赖自动降级 demo, 数据照常落库)
python -m finance.cli lance fetch --channel ccxt --instrument CRYPTO.BTC --time-level 1d

# 3. 配置自动获取定时任务
python -m finance.cli lance tasks --add --channel akshare --instrument CN.RB --every 1d

# 4. 挖掘新渠道
python -m finance.cli lance discovery --run

# 5. 查看数据/统计
python -m finance.cli lance data --stats
python -m finance.cli lance data --instrument CRYPTO.BTC --limit 10
```

## 六、渠道获取脚本 (分渠道解耦)

每个渠道一个模块，位于 `finance/crawler/fetchers/`，统一暴露 `fetch(store, payload) -> dict`：

| 渠道 | 模块 | 获取方式 | 说明 |
|---|---|---|---|
| akshare | `akshare_fetcher.py` | python 库 | A股/期货/宏观，无依赖降级 demo |
| yfinance | `yfinance_fetcher.py` | python 库 | 全球股票/外汇 |
| ccxt | `ccxt_fetcher.py` | python 库 | 100+ 加密交易所 |
| fred | `fred_fetcher.py` | HTTP API | 美联储宏观指标 |
| finnhub | `finnhub_fetcher.py` | HTTP API | 全球新闻/情绪 (需 key) |
| alpha_vantage | `alpha_vantage_fetcher.py` | HTTP API | 全球行情 (需 key) |
| rss_news | `rss_fetcher.py` | RSS 解析 | 财经舆论聚合 |
| cnb-sitemap | `cnb_sitemap_fetcher.py` | HTTP 爬虫 | CNB 平台公开信息 |
| manual | `manual_fetcher.py` | 人工录入 | 无法自动获取的数据 |

渠道新增 fetcher 时，在 `finance/crawler/fetchers/__init__.py` 的 `FETCHER_MODULES` 与 `CHANNEL_TO_MODULE` 注册即可。

## 七、参数体系 (params 表 scope)

| scope | 说明 | 示例 |
|---|---|---|
| channel | 渠道级默认参数 | feeds(RSS源列表), request_interval, url |
| instrument | 品种级参数 | symbol(akshare: RB0, ccxt: BTC/USDT), series_id(FRED) |
| fetcher | 获取器级参数 | ak_method, timeframe |
| request | 请求级参数 | timeout, max_retries, headers |
| storage | 存储配置 | table, partition |
| schedule | 调度配置 | default_frequency, default_cron |
| feature | 特征/衍生参数 | 扩展用 |
