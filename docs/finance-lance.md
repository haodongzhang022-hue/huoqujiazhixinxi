# LanceDB 统一数据管理层 (Finance LanceDB Layer)

> 对齐 Issue #6 二期需求：**数据用 LanceDB 数据库**，脚本统一管理「数据地址 / 列名 / 获取方式 / 获取脚本」，爬虫**解耦**为「通用模板 + 分渠道定义 + 参数特征记录」。

完整文档见 [finance/lance/README.md](../finance/lance/README.md)。

## 核心设计：解除耦合

```
┌─ 1. 爬虫通用部分 (finance/crawler/) ──────────────┐
│  base.py       请求/重试/限流/解析/分页 (通用引擎)  │
│  fields.py     标准字段映射与清洗                    │
│  dispatcher.py 渠道调度分发 -> 落库                 │
└────────────────────────────────────────────────────┘
                 ↓ 读取 (统一管理)
┌─ 2. 渠道定义文件 (LanceDB channels 表) ───────────┐
│  数据地址(source) / 获取方式(method) /              │
│  获取脚本(script/module) / 存储位置(storage)        │
└────────────────────────────────────────────────────┘
┌─ 3. 本渠道参数/特征 (LanceDB column_defs + params) ┐
│  列名映射: 渠道列 -> 标准字段 + 清洗规则             │
│  参数特征: channel/instrument/fetcher/request/...   │
└────────────────────────────────────────────────────┘
```

**新渠道 = 登记 3 类记录 + 可选自定义 fetcher，无需改通用代码。**

## 七张 LanceDB 表

| 表 | 用途 |
|---|---|
| `channels` | 渠道定义（数据地址/获取方式/获取脚本/存储位置） |
| `column_defs` | 本渠道列定义（原始列名 -> 标准字段） |
| `params` | 渠道/品种/获取器/请求/存储/调度 参数特征 |
| `fetch_tasks` | 自动获取数据定时任务 |
| `run_logs` | 运行日志 |
| `data_records` | 获取到的数据（标准字段宽表 + raw 原始行） |
| `discovery_candidates` | 渠道挖掘候选（发现→评估→转正） |

## 两个定时爬虫

### 1. 自动获取数据定时爬虫
```bash
python3 -m finance.cli lance tasks --add --channel akshare --instrument CN.RB --every 1d
python3 -m finance.cli lance tasks --add --channel ccxt --instrument CRYPTO.BTC --every 5m
python3 -m finance.cli lance tasks --run-due   # 扫描到期任务 (供 cron/CI 周期调用)
python3 -m finance.cli lance tasks --run-all   # 立即执行所有任务
```

### 2. 挖掘新渠道定时爬虫
```bash
python3 -m finance.cli lance discovery --run   # 一键: 发现+评估+自动转正
python3 -m finance.cli lance discovery --discover   # 仅发现
python3 -m finance.cli lance discovery --evaluate   # 探测打分
python3 -m finance.cli lance discovery --promote <candidate_id> --channel-id <id>  # 转正
```

## 快速开始

```bash
python3 -m finance.cli lance init                              # 建表 + 种子初始化(8渠道/28品种)
python3 -m finance.cli lance fetch --channel ccxt --instrument CRYPTO.BTC --time-level 1d
python3 -m finance.cli lance data --stats                      # 数据统计
python3 -m finance.cli lance data --instrument CRYPTO.BTC --limit 10
```

## 测试

```bash
python3 -m pytest tests/test_lance.py -q    # LanceDB 管理层 11 项
python3 -m pytest tests/ -q                 # 全量 53 项 (含原有储备库)
```
