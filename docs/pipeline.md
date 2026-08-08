# 开源项目信息获取与筛选管道 (huoqujiazhixinxi)

> 整合 wvb-cc-radar fetch 分层查询模型 + 条件判断分类 + LanceDB 储备库 + 条件触发引擎。
> 目标：**每天自动获取 GitHub 新/热项目 → 归一化去重 → 功能索引 → 三分类筛选 → 存入 LanceDB 储备库 → 条件触发按需调用**。

```
GitHub Search API (8 生态分类 × T1/T2/T3/T4 分层查询 + seed allowlist)
        │  pipeline/fetch.py (wvb-cc-radar 模型改造)
        ▼
每日快照 JSON (stars_delta_24h/7d + 冷启动推断 + action_candidate + needs 粗匹配)
        │  reserve/preprocessor.py (归一化 + 去重)
        ▼
reserve/classifier.py (打分模型 → action/reserve/partial/ignore 三分类 + 功能索引)
        │  reserve/embedding.py (本地中英桥接向量化 / API embedding)
        ▼
LanceDB 储备库 (repo_reserve 表: 功能索引 + 条件判断 + embedding)
        │
        ├── reserve/search.py  全文/向量/混合检索 ("人找货")
        ├── reserve/trigger.py 条件触发引擎 AUTO/SUGGEST/LOG ("货找货" + needs 双向生长回路)
        └── reserve/api.py     REST API (/api/v1/reserve/* + /api/v1/needs)
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r pipeline/requirements.txt
# 可选: 更强 embedding/功能索引 (配置 OPENAI_API_KEY 或 GEMINI_API_KEY)
```

### 2. 采集 (真实 GitHub API)

```bash
# 全量 8 分类 (~90 仓库/日, 建议配 GITHUB_TOKEN)
python -m pipeline.fetch

# 调试: 只采 12 个 (省配额)
python -m pipeline.fetch --limit 12

# 演示数据 (无网环境体验全流程)
python -m reserve.ingest --snapshot pipeline/data/snapshots/demo-2026-08-08.json
```

### 3. 入库 (归一化 → 去重 → 分类 → 向量化 → LanceDB)

```bash
python -m reserve.ingest
# LANCE_DIR=/path/to/reserve python -m reserve.ingest   # 指定储备库位置
```

### 4. 检索 ("人找货")

```bash
python -m reserve.search "需要 RAG 向量检索能力"
python -m reserve.search "MCP server" --top 5 --decision reserve
python -m reserve.search "压缩 token 的开源库" --mode vector
```

### 5. 条件触发 ("货找货" — 生态需求信号 → 自动决策)

```bash
python -m reserve.trigger "需要一个 MCP agent 智能体工具"
python -m reserve.trigger --rematch        # 重匹配 pending_needs (新项目入库后)
python -m reserve.trigger --needs          # 查看未满足需求
```

### 6. REST API

```bash
python -m reserve.api --port 8000
curl http://127.0.0.1:8000/api/v1/health
curl "http://127.0.0.1:8000/api/v1/reserve/search?q=mcp"
curl -X POST http://127.0.0.1:8000/api/v1/reserve/trigger \
  -H "Content-Type: application/json" -d '{"query":"需要 RAG 向量检索能力"}'
```

## 核心设计

### fetch 采集层 (wvb-cc-radar 模型改造)

| 原版 (wvb-cc-radar) | 本仓库改造 |
|---|---|
| 8 类 Claude Code 专属分类 | **8 类通用技术生态** (mcp-servers/ai-agents/rag-kb/agent-orchestration/llm-prompts/ai-dev-tools/data-infra/developer-tools) |
| T1/T2/T3 三层防漏查询 | **保留 + T4 新仓库扫描** (created:>7d, 激活冷启动 action 路径) |
| 韩语翻译 | **中文功能索引占位** (classifier 步骤填充) |
| korean-owners allowlist | **seed allowlist** (data/seeds/*.json 强制直连) |
| 24h/7d 双基线增量 | **保留 + 冷启动推断** (新仓库 delta≈stars) |

### 条件判断机制 (调研报告 §5.3)

```
score = 增长信号(24h爆发+3 / 7d走红+3 / 当周新+1 / 稳定高星+1)
      + 生态匹配(+2) + 质量信号(活跃+1 / 未归档+1)

score≥7 且 生态匹配≥0.5  → action (生态升级: 生成候选 PR 流程)
score≥4                → reserve (储备索引: 保留链接+功能索引)
生态匹配达标但增长不足   → partial (部分采用)
否则                    → ignore (忽略)
```

规则热更新: 修改 `config/reserve_rules.json` 即可 (阈值/权重/生态关键词)。

### 条件触发引擎 (AUTO/SUGGEST/LOG)

- **AUTO** (≥0.72): 强匹配 → 返回可执行方案 (clone_and_evaluate)
- **SUGGEST** (≥0.42): 部分满足 → 返回缺口分析 (missing keywords + advice)
- **LOG**: 无命中 → 记录进 pending_needs → 新项目入库时自动重匹配 (双向生长回路)

中文需求 → 英文仓库跨语言匹配: `reserve/embedding.py` 内置 70+ 中英术语映射
(量子→quantum, 向量→vector, 知识库→knowledge-base, ...)。

### LanceDB 储备库 Schema (repo_reserve 表)

核心字段: `repo_id`(唯一键) / `full_name` / `stars_delta_24h` / `stars_delta_7d` /
`function_tags` / `function_summary` / `use_case` / `ecosystem_fit` /
`category_decision`(action/reserve/partial/ignore) / `decision_score` / `decision_reason` /
`embedding`(vector[384]) / `matched_needs` / `search_text`(FTS 全文检索列)。

## 目录结构

```
pipeline/
├── config.py          8 生态分类 + T1/T2/T3/T4 分层查询配置 (wvb-cc-radar 泛化)
├── github_client.py   GitHub API 客户端 (5s/15s 退避重试, 配额跟踪)
├── fetch.py           采集主管道 (归一化 + 增量 + 冷启动 + needs 回路 + 落盘)
├── requirements.txt   运行依赖
└── data/
    ├── seeds/         每类 allowlist (强制直连)
    ├── snapshots/     每日快照 (YYYY-MM-DD.json)
    └── needs.json     pending_needs (可选)

reserve/
├── store.py           LanceDB 存储层 (repo_reserve / repo_snapshots / needs)
├── preprocessor.py    归一化 + 去重
├── classifier.py      打分三分类 + 功能索引 (LLM/启发式)
├── embedding.py       向量化 (本地中英桥接 / API)
├── ingest.py          fetch→classify→embed→入库 端到端管道
├── search.py          全文/向量/混合检索
├── trigger.py         条件触发引擎 + needs 双向生长回路
└── api.py             REST API 服务

config/
└── reserve_rules.json 条件判断规则 (热更新)

tests/
└── test_reserve.py    单元测试 (11 项, 无需 pytest)

.github/workflows/
└── daily-fetch.yml    每日 08:00 定时采集+入库+重匹配
```

## 测试

```bash
python tests/test_reserve.py    # 11/11 通过
```

## 环境变量

| 变量 | 说明 |
|---|---|
| `GITHUB_TOKEN` | GitHub API token (有则 5000 req/hr, 无则匿名 60 req/hr) |
| `LANCE_DIR` / `LANCEDB_URI` | LanceDB 存储位置 (默认 `./reserve_data`) |
| `RESERVE_TABLE` / `SNAPSHOT_TABLE` | 自定义表名 |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | LLM 功能索引 / API embedding (可选) |
| `PIPELINE_NEEDS_FILE` | pending_needs 文件路径 (可选) |

## 路线图 (R1-R7)

- [x] R1 储备库骨架 (LanceDB repo_reserve 表 + 条件判断字段)
- [x] R2 fetch 采集层 (wvb-cc-radar 模型改造, 本仓库)
- [x] R3 preprocessor + classifier (归一化/去重/三分类/功能索引)
- [x] R4 定时调度 (GitHub Actions daily-fetch.yml)
- [x] R6 条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)
- [x] R7 REST API 服务 (/api/v1/reserve/* + /api/v1/needs)
- [ ] R5 action 生态升级自动克隆注册 (候选 PR 半自动流程)
- [ ] LLM 功能索引接入 (function_tags/summary/use_case 高质量生成)
- [ ] 多源聚合 (agents-radar 适配 + 中文榜 + GH Archive 冷启动回填)
