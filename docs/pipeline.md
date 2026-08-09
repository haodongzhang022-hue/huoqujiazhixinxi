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
        ├── reserve/quality.py 内容质量评估 (快照/储备库/趋势 + 每日质量报告)
        ├── reserve/self_heal.py 管道自愈合 (健康检查 → 诊断 → 自动修复 → 事件日志)
        ├── reserve/dashboard.py 内容结构化整理视图 (总览/列表/能力簇/质量/快照/需求/审核)
        └── reserve/api.py     REST API (/api/v1/reserve/* + /api/v1/needs + /api/v1/quality + /api/v1/health|heal + /api/v1/dashboard/*) + Web 管理页面 (web/)
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

### 7. 质量评估 ("每天获取的内容质量怎么样了")

```bash
# 今日快照质量
python -m reserve.quality --snapshot pipeline/data/snapshots/YYYY-MM-DD.json
# 储备库整体质量
python -m reserve.quality --store
# 多日质量趋势
python -m reserve.quality --trend --days 7
# 每日综合报告 (快照 + 储备库 + 趋势, 写入 data/reports/)
python -m reserve.quality --report
```

### 8. 自愈合 (管道自动修复)

```bash
# 健康检查 (只检查不修复)
python -m reserve.self_heal --check-only
# 自动修复 (快照缺失→重采集, 索引缺失→重建, 临时文件→清理, LLM 不可用→降级)
python -m reserve.self_heal
# 查看愈合历史
python -m reserve.self_heal --log
```

### 9. Web 管理页面 + 展示 API ("内容整理好显示到页面")

```bash
python -m reserve.api --port 8000
# 浏览器打开 http://127.0.0.1:8000/ 即可看到管理台
# 页面功能: 总览 / 仓库列表 / 能力簇 / 质量评估 / 每日快照 / 需求 / 审核队列 / 自愈中心
```

结构化展示 API（页面与第三方共用）：

```bash
curl http://127.0.0.1:8000/api/v1/dashboard/overview       # 总览
curl "http://127.0.0.1:8000/api/v1/dashboard/repos?decision=action&sort=stars&limit=20"  # 仓库列表
curl http://127.0.0.1:8000/api/v1/dashboard/clusters       # 能力簇
curl http://127.0.0.1:8000/api/v1/dashboard/snapshots      # 每日快照
curl http://127.0.0.1:8000/api/v1/dashboard/needs          # 待满足需求
curl http://127.0.0.1:8000/api/v1/dashboard/review         # 审核队列
curl http://127.0.0.1:8000/api/v1/quality                  # 质量综合报告
curl http://127.0.0.1:8000/api/v1/quality/trend            # 质量趋势
curl http://127.0.0.1:8000/api/v1/health                   # 健康检查
curl -X POST http://127.0.0.1:8000/api/v1/heal -H "Content-Type: application/json" -d '{"check_only":false}'  # 自愈
```

## 核心设计

### 内容质量评估 (quality.py)

回答「每天获取的内容质量怎么样了」。三级质量视角 + 0~100 综合分：

| 维度 | 权重 | 说明 |
|---|---|---|
| completeness | 30% | 关键字段完整度 (description/topics/language/license/stars...) |
| freshness | 25% | 当日新仓库占比 / 7d 有增量仓库占比 |
| richness | 20% | 分类覆盖 / 唯一仓库数 / 去重后结构 |
| index_health | 15% | function_tags / summary / use_case 覆盖率 |
| decision_health | 10% | 分类分布合理性 / action 候选占比 / review 通过率 |

分级: A (≥90) / B (≥75) / C (≥60) / D (<60)。
质量报告持久化到 `data/reports/YYYY-MM-DD.json`，供页面趋势图与追溯。

### 自愈合 (self_heal.py)

检测 → 诊断 → 修复 → 记录 四步闭环：

| 检测项 | 严重度 | 自愈动作 |
|---|---|---|
| 今日快照缺失 | high | 自动重采集 (fetch + 写盘 + 入库) |
| 快照损坏/过半分类空 | high | 自动重采集 |
| 快照过期 (>2 天) | medium | 自动重采集 |
| GitHub 配额不足 | medium | 记录等待 (跳过) |
| 储备库为空 | medium | 尝试入库最近快照 |
| FTS 索引缺失 | low | 自动重建索引 |
| LLM 不可用 | low | 降级启发式 + 人工审核队列 |
| 临时文件堆积 | low | 自动清理 |

策略可配置 (`config/self_heal.json`)：`auto_refetch` / `refetch_limit` / `rebuild_fts` / `clean_temp`。
愈合事件持久化到 `data/heal_log.json`（保留 30 天），页面「自愈中心」可查看。

### Web 管理页面 + 展示视图 (dashboard.py + web/)

「当前获取的内容应该好好整理，有结构，然后再把内容到页面」——
所有展示数据由 `reserve/dashboard.py` 统一整理为结构化 JSON，
`web/` 提供零依赖纯静态管理台（原生 HTML/JS/CSS，无构建步骤）：

| 页面 | 数据来源 API | 内容 |
|---|---|---|
| 总览 | /api/v1/dashboard/overview | 统计卡片 / 决策分布 / 分类分布 / 质量趋势图 / 快照列表 / 审核队列 / 需求 |
| 仓库列表 | /api/v1/dashboard/repos | 分页 + 过滤 (decision/category/tag/q) + 排序 (stars/delta7d/newest/score) |
| 能力簇 | /api/v1/dashboard/clusters | 按功能标签聚类的能力簇卡片 (每簇: 项目/星数/决策) |
| 质量评估 | /api/v1/quality | 快照 + 储备库 + 趋势 三维质量报告与建议 |
| 每日快照 | /api/v1/dashboard/snapshots | 最近 30 天快照的质量分/数量/问题 |
| 需求 | /api/v1/dashboard/needs | pending_needs 列表 + 一键重匹配 |
| 审核队列 | /api/v1/dashboard/review | action 候选审核 + 通过/拒绝操作 |
| 自愈中心 | /api/v1/health + /api/v1/heal + /api/v1/heal/log | 健康检查 / 一键自愈 / 愈合日志 |

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
├── store.py           LanceDB 存储层 (repo_reserve / repo_snapshots / needs, 动态向量维度)
├── preprocessor.py    归一化 + 去重
├── classifier.py      打分三分类 + 功能索引 (LLM/启发式)
├── embedding.py       向量化 (本地中英桥接 / OpenAI 兼容 / Ollama API)
├── llm.py             LLM Provider 抽象层 (OpenAI 兼容 API / 本地 Ollama / 自定义端点)
├── enrich.py          LLM 功能索引生成 (读 README/发布者介绍 → 高质量索引)
├── review.py          LLM 代码审核 (action 候选四维评审) + 人工审核队列
├── cluster.py         能力聚类 (按功能标签 / 向量 K-means, 能力簇视图)
├── quality.py         内容质量评估 (快照/储备库/趋势 + 每日质量报告)
├── self_heal.py       管道自愈合 (健康检查 → 诊断 → 自动修复 → 事件日志)
├── dashboard.py       内容结构化整理视图 (总览/列表/能力簇/质量/快照/需求/审核)
├── ingest.py          fetch→classify→LLM增强→LLM审核→embed→入库 端到端管道
├── search.py          全文/向量/混合检索
├── trigger.py         条件触发引擎 + needs 双向生长回路
└── api.py             REST API (含 /api/v1/llm/status + /api/v1/review/* + /api/v1/reserve/cluster
                       + /api/v1/quality + /api/v1/health|heal + /api/v1/dashboard/* + Web 页面托管)

web/
├── index.html         管理台入口 (总览/仓库列表/能力簇/质量/快照/需求/审核/自愈)
├── app.js             前端逻辑 (原生 JS, 调用 /api/v1/dashboard/*)
└── style.css          管理台样式 (深色主题)

config/
├── reserve_rules.json 条件判断规则 (热更新)
├── self_heal.json     自愈合策略 (自动重采集/重建索引/清理开关)
├── llm.json           自定义 LLM 配置 (API/本地模型, 不入库)
└── llm.json.example   配置模板

data/
├── reports/           每日质量报告 (YYYY-MM-DD.json)
└── heal_log.json      自愈事件日志 (保留 30 天)

tests/
└── test_reserve.py    单元测试 (34 项, 无需 pytest)

.github/workflows/
└── daily-fetch.yml    每日 08:00 定时采集+入库+质量评估+自愈+重匹配
```

## 测试

```bash
python tests/test_reserve.py    # 34/34 通过
```

## LLM 接入（自定义 API / 本地大模型）

> 功能索引高质量生成、读 README/发布者介绍、代码审核——都需要大模型。
> 本仓库已内置 **LLM Provider 抽象层**（`reserve/llm.py`, 零第三方依赖, 标准库 urllib 直连），
> 支持接入**任意 OpenAI 兼容 API** 或**本地 Ollama**，也支持人工 `@CodeBuddy` 审核队列。

### 方式一：OpenAI 兼容 API（任意自定义端点）

适用于 OpenAI / DeepSeek / Moonshot Kimi / 通义千问 / OneAPI 网关 / vLLM / LM Studio……
只要实现 `POST {base_url}/chat/completions` 即插即用：

```bash
# 环境变量方式
LLM_BASE_URL=https://api.deepseek.com/v1 \
LLM_API_KEY=sk-xxx \
LLM_MODEL=deepseek-chat \
python -m reserve.ingest

# 或写入 config/llm.json（推荐, 持久化）
# { "provider": "openai", "base_url": "https://api.deepseek.com/v1",
#   "api_key": "sk-xxx", "model": "deepseek-chat" }
```

### 方式二：本地 Ollama（完全离线）

```bash
# 先拉模型: ollama pull qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434 \
OLLAMA_MODEL=qwen2.5:7b \
python -m reserve.ingest
```

### 方式三：人工 / @CodeBuddy 审核队列（不配 LLM 也能用）

未配置 LLM 时, action 候选自动进入 `config/review_queue.json` 人工审核队列,
可随时在本仓库 `@CodeBuddy` 召唤 NPC 审核: 人工确认后 `review_status=approved` 才进入生态升级。

```bash
python -m reserve.review queue            # 查看审核队列
python -m reserve.review update owner/repo approved --note "人工通过"  # 确认/拒绝
curl http://127.0.0.1:8000/api/v1/review/queue   # REST 查看
curl -X PUT "http://127.0.0.1:8000/api/v1/review/queue/owner/repo?status=approved"
```

### LLM 配置摘要

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `LLM_PROVIDER` | auto / openai / ollama / none | auto |
| `LLM_BASE_URL` | OpenAI 兼容端点 (含 /v1) | 空 |
| `LLM_API_KEY` | API key (本地 vLLM/Ollama 可留空) | 空 |
| `LLM_MODEL` | 模型名 | 空 |
| `OLLAMA_BASE_URL` | 本地 Ollama 地址 | http://localhost:11434 |
| `OLLAMA_MODEL` | 本地模型名 | qwen2.5:7b |
| `LLM_TIMEOUT` | 请求超时秒数 | 90 |
| `LLM_TEMPERATURE` | 采样温度 | 0.2 |

## LLM 功能索引（enrich）

读**仓库元数据 + README（发布者介绍）** → 生成四字段中文索引：

- `function_tags`：功能标签（MCP / AI-Agent / RAG / LLM / 知识库 / … 白名单引导）
- `function_summary`：一句话中文总结（解决什么问题）
- `use_case`：适用场景（什么时候应该用它）
- `ecosystem_fit`：与 MCP/AI-Agent/RAG/LLM 生态匹配度分析

```bash
python -m reserve.enrich 快照.json --readme     # 独立运行 (拉 README 增强)
python -m reserve.ingest                        # 管道内自动启用 (--no-llm 关闭)
```

## LLM 代码审核（review）

对 **action 候选（生态升级）** 仓库做四维 LLM 评审：

1. 功能匹配（是否真的解决我们的问题）
2. 代码质量与活跃度（维护/star 增长/文档）
3. 许可证合规（MIT/Apache 优, GPL 提示, 无协议告警）
4. 生态适配（接入 MCP/AI-Agent/RAG/LLM 难度与依赖风险）

输出 `verdict: approve / condition / reject / manual` + `score 0-10` + `risks` + `recommendation`，
结果持久化到 LanceDB（`review` / `review_status` 字段）并进入人工审核队列，
人工/`@CodeBuddy` 确认后才算生态升级通过。

```bash
python -m reserve.review review 快照.classified.json   # 审核 action 候选
python -m reserve.review queue                          # 查看队列
```

## 能力聚类（cluster）

对储备库做「聚类分类 + 列出功能 + 调用时机」的能力簇视图（对齐 Issue 需求）：

```bash
# 按功能标签聚类 -> 能力簇索引 (标签/项目/总星数/功能摘要)
python -m reserve.cluster --by-tags
# 向量语义聚类 (纯 Python K-means, 无需 sklearn)
python -m reserve.cluster --kmeans --k 6
# 对未入库的快照先分类再聚类
python -m reserve.cluster --snapshot pipeline/data/snapshots/YYYY-MM-DD.json
# JSON 输出 (供上层应用消费)
python -m reserve.cluster --kmeans --json
```

REST API: `GET /api/v1/reserve/cluster?mode=by-tags|kmeans&k=6`

## 环境变量

| 变量 | 说明 |
|---|---|
| `GITHUB_TOKEN` | GitHub API token (有则 5000 req/hr, 无则匿名 60 req/hr) |
| `LANCE_DIR` / `LANCEDB_URI` | LanceDB 存储位置 (默认 `./reserve_data`) |
| `RESERVE_TABLE` / `SNAPSHOT_TABLE` | 自定义表名 |
| `LLM_*` / `OLLAMA_*` | LLM 接入配置 (见上表) |
| `EMBEDDING_API_KEY` / `EMBEDDING_API_URL` / `EMBEDDING_MODEL` | API embedding (可选, 更强) |
| `RESERVE_EMBED_DIM` | 储备库向量维度 (默认自动跟随 embedding 模型推断) |
| `PIPELINE_NEEDS_FILE` | pending_needs 文件路径 (可选) |
| `REVIEW_QUEUE` | 人工审核队列文件路径 (可选, 默认 config/review_queue.json) |
| `HEAL_LOG` | 自愈事件日志路径 (可选, 默认 data/heal_log.json) |
| `REPORT_DIR` | 质量报告目录 (可选, 默认 data/reports/) |

## 路线图 (R1-R8)

- [x] R1 储备库骨架 (LanceDB repo_reserve 表 + 条件判断字段)
- [x] R2 fetch 采集层 (wvb-cc-radar 模型改造, 本仓库)
- [x] R3 preprocessor + classifier (归一化/去重/三分类/功能索引)
- [x] R4 定时调度 (GitHub Actions daily-fetch.yml)
- [x] R6 条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)
- [x] R7 REST API 服务 (/api/v1/reserve/* + /api/v1/needs)
- [x] R8 LLM 接入 (自定义 API/本地 Ollama) + LLM 功能索引 + LLM 代码审核 + 人工审核队列
- [x] R9 能力聚类 (按功能标签 / 向量 K-means, 能力簇索引视图)
- [x] R10 内容质量评估 (快照/储备库/趋势 + 每日质量报告, 0~100 综合分 A-D 分级)
- [x] R11 管道自愈合 (健康检查 → 自动修复 → 事件日志, 快照缺失自动重采集)
- [x] R12 Web 管理页面 + 结构化展示 API (总览/仓库列表/能力簇/质量/快照/需求/审核/自愈)
- [ ] R5 action 生态升级自动克隆注册 (候选 PR 半自动流程, 消费 review_status=approved)
- [ ] 多源聚合 (agents-radar 适配 + 中文榜 + GH Archive 冷启动回填)
