# 全球金融数据超索引框架 (Finance Data Source Super Index)

> 对齐 Issue #6：**对全球各个方面金融数据的总框架** —— 一个管理"数据获取能力"的超大索引框架。

## 核心思想

```
全球金融数据
  = 数据类别 × 国家/地区 × 交易所/市场 × 时间级别 × 品种 × 交易类型   (六维分类)
    ↓
  筛选器 (filter)                                                  (任意维度组合定位)
    ↓
  索引到目标品种 + 匹配到数据源获取脚本                              (每个分类不同的获取方式)
    ↓
  渐进式披露: index(索引) → meta(元数据) → full(全量)               (聚类/分类/渐进披露)
    ↓
  触发获取 / 定时自动获取 (频率/时间)                                (调度器)
```

## 六大维度（分类体系 taxonomy）

| 维度 | 说明 | 示例 |
|---|---|---|
| `data_class` 数据类别 | 资产大类 | stock 股票 / futures 期货 / forex 外汇 / crypto 区块链 / macro 宏观 / sentiment 舆论 / bond 债券 / fund 基金 / realestate 房地产 / commodity 大宗现货 |
| `region` 国家/地区 | 13 个地区 | CN / HK / US / JP / KR / TW / SG / EU / UK / DE / FR / AU / GLOBAL |
| `exchange` 交易所/市场 | 43 个市场 | SSE SZSE HKEX NASDAQ NYSE SHFE DCE CZCE INE CME LME BINANCE OKX FRED NBS ... |
| `time_level` 时间级别 | 16 级 | tick 1s 5s 15s 30s 1m 5m 15m 30m 1h 4h 1d 1w 1M 1Q 1Y |
| `instrument` 品种 | 28 个示例标的 | CN.RB 螺纹钢 / US.AAPL 苹果 / CRYPTO.BTC 比特币 / FX.USDCNY / MACRO.US.CPI ... |
| `trade_type` 交易类型 | 9 类 | spot 现货 / contract 合约 / perpetual 永续 / option 期权 / forward 远期 / swap 掉期 / cfd / etf / indices 指数 |

## 数据源目录（catalog：每个分类不同的获取方式）

`config/finance/catalog.json` 注册了 9 类数据源，每个数据源声明：
**覆盖范围 + 获取脚本(script/module/command) + 调度策略 + 渐进披露级别 + 数据落地 + 依赖**。

| 数据源 | 类型 | 覆盖 | 获取方式 | 依赖 | 状态 |
|---|---|---|---|---|---|
| `akshare` | python_lib | 中国及全球行情（A股/港股/期货/基金/宏观/汇率） | 脚本 `finance/fetchers/akshare_fetcher.py` | pip install akshare | demo |
| `yfinance` | python_lib | 全球股票/ETF/外汇/期货 | `yfinance_fetcher.py` | pip install yfinance | demo |
| `ccxt` | python_lib | 加密货币 100+ 交易所现货/合约/永续/期权 | `ccxt_fetcher.py` | pip install ccxt | demo |
| `fred` | http_api | 美国及全球宏观/利率/债券序列 | `fred_fetcher.py` (urllib 直连) | FRED_API_KEY | demo |
| `finnhub` | http_api | 全球新闻+行情+情绪 | `finnhub_fetcher.py` | FINNHUB_API_KEY | demo |
| `rss_news` | rss | 财经舆论聚合（新华/东财/路透/CNBC） | `rss_fetcher.py` | feedparser（可降级标准库） | demo |
| `alpha_vantage` | http_api | 全球股票/外汇/宏观/加密 | `alpha_vantage_fetcher.py` | ALPHA_VANTAGE_API_KEY | demo |
| `github` | http_api | 全球开源项目生态/开发者舆论（活跃榜 + 单项目 stars/forks/提交） | `github_fetcher.py` (标准库 urllib 直连) | 无需 Key | **live（真实数据）** |
| `manual` | manual | 人工/半自动录入 | `manual_fetcher.py` | 无 | demo |

> **框架特性**：未安装依赖/未配 Key 时自动降级为 demo 模式（本地生成模拟数据），
> 框架**离线可运行**；接入真实 API 后自动切换真实数据。
>
> ✅ **`github` 是首个 `status: live` 的真实数据源**：GitHub 公开 API 无需 Key、网络实测可达（HTTP 200，限流 60 次/小时），
> 通过标准库 `urllib` 直连即可获取真实开源项目数据（star/forks/活跃度/近期提交），
> 证明框架"**能获取真实信息**"而非仅 demo 模拟。

## 渐进式披露（disclosure）

| 级别 | 内容 | 成本 | 触发 |
|---|---|---|---|
| `index` L0 | 品种/数据源/缓存文件轻量索引 | 无（不触发获取） | `GET /disclosure/index?instrument=CN.RB` |
| `meta` L1 | 品种索引卡 + 可用数据源 + 缓存状态 | 无（读本地） | `GET /disclosure/meta?instrument=CN.RB` |
| `full` L2 | 完整数据（触发获取脚本或读缓存） | 有（联网/API 配额） | `POST /fetch` / `--refresh` |

## 调度器（scheduler：频率/时间/自动获取）

- 每个任务 = (数据源, 品种, 时间级别, 交易类型)
- 调度类型：`every` 频率（5m/1h/1d/2d）· `at` 每天时刻（HH:MM）· manual（手动）
- 任务持久化 `finance/data/scheduler.json`，支持 `--daemon` 常驻守护、`--run-once` 单次扫描

## 快速开始

```bash
# 1. 查看分类体系
python3 -m finance.taxonomy --stats

# 2. 六维筛选: 中国期货
python3 -m finance.cli search --data-class futures --region CN

# 3. 筛选 + 聚类统计
python3 -m finance.cli search --instrument BTC --summary

# 4. 渐进披露: index → meta → full
python3 -m finance.cli index --instrument CN.RB
python3 -m finance.cli meta --instrument CN.RB
python3 -m finance.cli fetch --instrument CN.RB --source akshare --time-level 1d

# 4b. ✅ 真实数据示例 (GitHub 开源生态, 无需 Key, 网络可达即返回真实数据):
python3 -m finance.cli search --data-class sentiment --region GLOBAL   # 六维筛选定位 GitHub 品种
python3 -m finance.cli fetch --instrument SENTIMENT.GITHUB.PYTORCH --source github --time-level 1d   # 真实 stars/forks/近期提交
python3 -m finance.cli fetch --instrument SENTIMENT.GITHUB.TRENDING --source github --time-level 1d  # 真实开源活跃榜

# 5. 调度: 每天 16:00 自动获取
python3 -m finance.cli schedule --add --instrument CN.RB --source akshare --every 1d --at 16:00
python3 -m finance.cli schedule --list
python3 -m finance.cli schedule --run-once      # 单次扫描执行到期
python3 -m finance.cli schedule --daemon        # 常驻守护

# 6. REST API + Web 管理台
python3 -m finance.api --port 8100
# 浏览器打开 http://127.0.0.1:8100/ 或
# curl "http://127.0.0.1:8100/api/v1/finance/search?data_class=crypto&trade_type=perpetual"
```

## REST API 一览

```
GET  /api/v1/finance/health                         健康检查
GET  /api/v1/finance/taxonomy/stats                 分类统计
GET  /api/v1/finance/exchanges?region=CN            交易所查询
GET  /api/v1/finance/instruments?data_class=&region=  品种筛选
GET  /api/v1/finance/instruments/{id}               品种索引卡
GET  /api/v1/finance/catalog                         数据源目录
GET  /api/v1/finance/catalog/{source}/script         数据源获取脚本
GET  /api/v1/finance/search?...                       六维筛选
GET  /api/v1/finance/disclosure/{index|meta|full}?instrument=  渐进披露
POST /api/v1/finance/fetch                            触发获取
GET/POST /api/v1/finance/schedule                     调度管理
DELETE /api/v1/finance/schedule/{id}                  删除任务
POST /api/v1/finance/schedule/run-once                执行到期
GET  /api/v1/finance/cache                            缓存文件
```

## 目录结构

```
config/finance/
├── taxonomy.json        六维分类体系 (数据类别/国家/交易所/时间级别/交易类型/品种)
└── catalog.json         数据源注册目录 (覆盖范围 + 获取脚本 + 调度 + 披露级别)

finance/
├── taxonomy.py          分类体系加载与查询
├── catalog.py           数据源目录
├── filter.py            筛选器 (六维组合定位)
├── disclosure.py        渐进式披露 (index/meta/full)
├── registry.py          获取器注册表 (脚本 -> 适配器, demo 降级, 缓存落盘)
├── scheduler.py         调度器 (频率/时间/自动获取)
├── api.py               REST API
├── cli.py               CLI 统一入口
├── fetchers/            每个分类的获取脚本 (akshare/yfinance/ccxt/fred/finnhub/rss/alpha_vantage/github/manual)
├── web/                 轻量 Web 管理台 (总览/筛选/目录/调度/缓存)
└── data/
    ├── cache/           获取数据落地缓存
    └── scheduler.json   调度任务持久化

tests/test_finance.py    框架测试 (10 项)
```

## 测试

```bash
python3 tests/test_finance.py    # 10/10 通过 (含 github 真实数据源; 网络不可用时优雅降级, 离线仍可运行)
```

## 扩展指南（接入新数据源 / 新品种）

1. **新品种**：在 `config/finance/taxonomy.json` 的 `instruments` 增加条目
   （id/symbol/name/exchange/data_class/trade_types），索引卡自动生成。
2. **新数据源**：在 `config/finance/catalog.json` 的 `sources` 增加条目
   （id/coverage/script/module/command/schedule/disclosure），并在 `finance/fetchers/`
   新建同名 `*_fetcher.py` 实现 `fetch(payload)`。无需改任何业务代码即可被筛选器索引。
3. **新数据类别/国家/交易所/时间级别/交易类型**：编辑 taxonomy.json 对应节即可。

## 后续路线图

- [x] **打通首条真实数据链路**（GitHub 开源生态：活跃榜 + 单项目 stars/forks/活跃度/近期提交，无需 Key、网络可达即返回真实数据）
- [ ] 接入更多真实数据源（Tushare/东财/新浪/雅虎/彭博/路透/EIA/OECD...）
- [ ] 数据落地升级：JSON 缓存 → SQLite / Parquet / LanceDB 储备库
- [ ] 行情数据统一 schema + 多源合并去重 + 质量评分（复用 reserve/quality.py 思路）
- [ ] 与开源项目储备库管道 (`reserve/`) 打通：舆论/新闻 → 情绪打分 → 事件驱动触发
- [ ] 定时任务接入 .cnb.yml / GitHub Actions cron
- [ ] 交易所日历（交易日/休市）、宏观数据发布日历
