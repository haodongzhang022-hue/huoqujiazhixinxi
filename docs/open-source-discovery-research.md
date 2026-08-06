# 开源项目获取能力调研报告：GitHub 每日新/热项目获取生态

> 调研人：CodeBuddy（@npc/CodeBuddy）
> 发起人：山东予路 张浩东（cnb.c8uGWZu7gHA）
> 调研时间：2026-08-06
> 目标：摸清 GitHub 开源项目「每日发现/获取」工具链的现状与成熟度；判断各项目是否具备**获取后的信息预处理**（如功能索引、分类、条件判断）；为后续「生态升级（直接采用）」+「储备库（LanceDB 索引）」两步走提供选型依据。

---

## 0. 结论速览（TL;DR）

| 维度 | 结论 |
|---|---|
| 市场成熟度 | 已进入**白热化阶段**：中英文社区均有大量「每日/每周获取 GitHub 新热项目」的项目，头部项目 10 万+ star（HelloGitHub 16.9 万）、4.7 万+（GitHubDaily） |
| 数据源 | 主要 4 类：GitHub Trending 官方页（爬虫）、GitHub Search/REST API、GH Archive 全量事件、人工策展（公众号/社区） |
| 预处理现状 | **普遍很弱**。绝大多数项目只做「采集 → 落盘 → 展示」；**只有少数项目做了分类、增量 diff、AI 翻译/改写、去重**；**没有任何项目做「条件判断机制 + 向量库索引 + 储备库」**，这正是我们的差异化机会 |
| 与 LanceDB 的结合 | 开源生态中**无现成先例**，需要我们自建：采集 → 结构化 → 向量化 → LanceDB 储备库 → 条件判断路由 |
| 推荐路线 | **数据管道**直接采用/自研（参考 wvb-cc-radar 的分层查询 + agents-radar 的多源聚合）；**内容加工**借鉴 HelloGitHub/GitHubDaily 的策展质量；**储备库架构**完全自建 |

---

## 1. 调研范围与方法

- 检索关键词：github trending / daily digest / awesome daily / HelloGitHub / GitHubDaily / discover new repos / repo radar / trendshift / 开源项目每日推荐 等 20+ 组
- 共筛选出 **15 个代表性项目** 做深度源码级检查（clone 到本地、读 README + 数据格式 + GitHub Actions 工作流）
- 评估维度：
  1. **数据源**（单一/多源、官方 API/爬虫）
  2. **更新频率**（每日/每周/每月，是否自动化）
  3. **信息预处理**（分类索引、增量 diff、翻译、去重、质量过滤、LLM 加工）
  4. **条件判断/路由机制**（有没有"什么时候用什么项目"的决策逻辑）
  5. **数据可解析性**（结构化 JSON / 半结构化 MD / 纯展示）
  6. **生态与可持续性**（star、license、活跃度）

---

## 2. 候选项目全景（15 个，按成熟度分层）

### 2.1 第一梯队：头部策展型（人工 + 自动化，质量最高）

| 项目 | Star | 更新 | 数据源 | 预处理 | 结构化程度 |
|---|---|---|---|---|---|
| [521xueweihan/HelloGitHub](https://github.com/521xueweihan/HelloGitHub) | 169,406 | 每月 28 号月刊 | 社区投稿 + 人工策展 | **语言分类**（C/C++/Go/Java/JS/Python/Rust/Swift…）、中文简介、推荐语 | 半结构化 MD（`### 语言` 分节 + `数字、[名称](跳转链接)：简介`，**正则可直接解析**，124 期实测 40 条/期） |
| [GitHubDaily/GitHubDaily](https://github.com/GitHubDaily/GitHubDaily) | 47,387 | 持续（日更公众号，仓库按年复盘） | 人工策展（运营 10 年） | **12 大分类索引**（AI 工具/学习教程/资料集合/实用工具/实用插件/媒体工具/开发工具/内容创作/编程语言库/在线服务/其他）、中文描述 | 半结构化 MD 表格（`[name](github链接)\|描述`，README 实测 1531 个可解析链接） |
| [OpenGithubs/github-monthly-rank](https://github.com/OpenGithubs/github-monthly-rank) | 1,473 | 每月 1 号 8 点自动 | GitHub API | 月榜 Top30、Star 增量排序、开源时间/描述 | 半结构化 MD（含「榜单增长第 N 名 + 开源地址/开源时间/总星标/月增长/描述」固定字段，**正则可解析**） |

**点评**：这三家是「内容策展」标杆。HelloGitHub 有**语言功能索引雏形**，GitHubDaily 有**12 大类功能索引**，OpenGithubs 有**增长指标**。但它们都是**给人看的**：人工写作、月刊/周更、无向量库、无条件判断机制。适合作为**我们内容质量的参照**和**历史语料**，不适合直接当数据管道。

### 2.2 第二梯队：自动化管道型（可编程、可二次开发，最适合"生态升级"）

| 项目 | Star | 更新 | 数据源 | 预处理 | 结构化程度 |
|---|---|---|---|---|---|
| [duanyytop/agents-radar](https://github.com/duanyytop/agents-radar) | 933 | 每日 08:00 CST 自动 | **10 源**（GitHub 17+ 仓库的 Issue/PR/Release、GitHub Trending、HN、Product Hunt、ArXiv、HuggingFace、Dev.to、Lobsters、Anthropic/OpenAI 站点） | **LLM 摘要（DeepSeek）**、中英双语、**AI 工具横向对比**、按主题分报告（ai-cli/ai-agents/ai-infra/ai-trending…）、**MCP Server 提供 list/search 检索**、RSS + Telegram/飞书推送、manifest 索引 | 高（MD 报告 + JSON manifest，结构良好） |
| [drwon-cmd/wvb-cc-radar](https://github.com/drwon-cmd/wvb-cc-radar) | 4（新） | 每日 09:00 KST + 15:00 备份 | GitHub Search API（**8 大分类 × 100 仓库**） | **三类：NEW 徽标（7 日内新建）、star 增量 24h/7d、AI 翻译（Gemini/Claude CLI）、WVB uses 标记（团队在用清单）**；三层查询防漏（T1 趋势 14d / T2 稳定 viral 60d / T3 永久 viral 高 star）；**数据 schema 完整（JSON：full_name/description/topics/stars_delta_24h/stars_delta_7d/description_ko/is_new_this_week）** | **高（每日 JSON 快照，2026-04 起持续归档 100+ 天）** |
| [bonfy/github-trending](https://github.com/bonfy/github-trending) | 1,081 | 每日自动 | GitHub Trending 页爬虫 | 无（仅按语言落盘 MD） | 低（MD 列表） |
| [larsbijl/trending_archive](https://github.com/larsbijl/trending_archive) | 394 | 每日自动 | GitHub Trending 页爬虫 | **增量 diff**（`*_short.md` 只存"今日新增"） | 中（MD，按 年/月/日 归档，2014 年起） |
| [vitalets/github-trending-repos](https://github.com/vitalets/github-trending-repos) | 2,988 | 每日/每周 | GitHub Trending 页爬虫 | 按语言分 issue 订阅、通知 | 低（Issue 评论） |
| [kujian/githubTrending](https://github.com/kujian/githubTrending) | 375 | 每日 | 自建爬虫（github.qdkfweb.cn） | 前端方向专题 + Issue 存档 | 低（MD + Issue） |
| [huchenme/github-trending-api](https://github.com/huchenme/github-trending-api) | 828 | 随请求 | GitHub Trending 页爬虫包装成 API | 无（纯数据服务） | 中（JSON API，**可作为数据源直接调用**） |

**点评**：这层是我们的**主战场**。其中：
- **wvb-cc-radar** 的「分层查询（T1/T2/T3）+ 增量指标 + 分类 schema + 团队 uses 标记」与我们「生态升级判断」的需求**高度同构**——它已经隐式回答了"哪些新项目值得进生态"（NEW + 高增量 + 团队在用）。
- **agents-radar** 的「多源聚合 + LLM 摘要 + MCP 检索」与「储备库 + 条件检索」的需求**高度同构**——它把"获取后的预处理"做成了可查询的服务。
- **trending_archive** 的「增量 diff」是储备库去重的现成范式。

### 2.3 第三梯队：周边/辅助型（可作为数据源或参考，不宜直接采用）

| 项目 | Star | 用途 |
|---|---|---|
| [PingCAP/ossinsight](https://github.com/PingCAP/ossinsight) | 2,482 | 100 亿+ 事件数据分析平台，Tidb + LLM NL2SQL。**可作为"新项目质量回溯验证"数据源**（查询项目 star 增速、开发者活跃度），不适合做轻量管道 |
| [GH Archive](https://www.gharchive.org/)（非 repo） | — | GitHub 全量公开事件流（每小时归档），**最权威的"每日新仓库"底层数据**，可离线分析（结合 DuckDB/Parquet）。适合做储备库的"冷启动全量回填" |
| [ChHsiching/GitHub-Chinese-Top-Charts](https://github.com/ChHsiching/GitHub-Chinese-Top-Charts) | 2,076 | 中文项目总榜+18 语言分榜，每周更新，**可作为中文项目质量池** |
| [begin0808/github-hot](https://github.com/begin0808/github-hot) | 21 | 每周聚合新建高星项目，Gemini 翻译成繁中并结构化（**features/applications 字段正是我们要的"功能描述 + 适用场景"**），周更 12 条 × 5 周期 |
| [Pangu-Immortal/hunter-ai-content-factory](https://github.com/Pangu-Immortal/hunter-ai-content-factory) | 383 | 内容工厂：GitHub/Twitter/Reddit/HN 采集 → Gemini 写作 → **ChromaDB 语义去重** → PushPlus 发布。**其"向量去重"思路可迁移到 LanceDB** |
| [521xueweihan/Hydra](https://github.com/HelloGitHub-Team/Hydra) | 236 | HelloGitHub 的 Python 爬虫框架（多平台账号信息采集），可参考采集实现 |

---

## 3. 关键发现：信息预处理能力横评

按"获取后做了多少加工"对候选项目打分（5 分制）：

| 预处理能力 | HelloGitHub | GitHubDaily | agents-radar | wvb-cc-radar | github-hot | trending_archive | hunter-ai | 说明 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| 分类/索引 | 4（按语言） | 5（12 大类） | 4（按主题报告） | 5（8 大分类 schema） | 3（按周期） | 2（按语言） | 2（按模板） | 有分类，但都**没有"功能索引"**（即"这个项目解决什么问题"的可检索字段） |
| 增量/去重 | 1 | 1 | 2 | 3（24h/7d delta） | 2 | 4（_short diff） | 4（ChromaDB 语义去重） | 只有 trending_archive / hunter 做了真正的去重 |
| 质量过滤 | 4（人工精选） | 4（人工精选） | 2 | 4（分层查询+star 门槛） | 3 | 1 | 2 | 人工策展质量最高，自动管道靠 star 阈值 |
| LLM 加工 | 1 | 1 | 5（DeepSeek 摘要+对比） | 4（Gemini/Claude 翻译） | 4（Gemini features/applications） | 1 | 5（Gemini 全流程写作） | agents-radar 与 github-hot 的 LLM 加工最有价值 |
| 条件判断/路由 | 1（人看） | 1（人看） | 2（MCP 检索） | 3（WVB uses 标记） | 1 | 1 | 1 | **全行业空白**：没有"什么时候该用这个项目"的机制化决策 |
| 结构化输出 | 2（MD） | 2（MD） | 4（MD+manifest） | 5（JSON schema） | 5（JSON） | 3（MD 但规则化） | 3（SQLite+ChromaDB） | wvb-cc-radar / github-hot 的 JSON 可直接喂 LanceDB |

**结论**：
1. **「分类索引」已有雏形**（HelloGitHub 按语言、GitHubDaily 按 12 大类、wvb-cc-radar 按 8 大技术分类），但都是**内容组织层面的分类，不是"功能索引"**——即没有把"项目能解决什么问题/什么场景适用"抽成可检索的功能描述（github-hot 的 `features`/`applications` 字段最接近）。
2. **「条件判断机制」在所有项目中都不存在**——没有项目回答"什么时候用 A 而不是 B、什么条件下值得吸收进生态"。这是我们可以建立的**核心差异化能力**。
3. **「储备库 + 向量库」无先例**——没有任何项目把新项目存进 LanceDB/向量库做长期储备。LanceDB 结合全文检索 + 向量检索的特性非常适合这个场景。

---

## 4. 选型建议（生态升级 + 储备库两步走）

### 4.1 直接纳入生态升级（管道层，代码级采用/改造）

| 用途 | 采纳对象 | 理由 | 改造点 |
|---|---|---|---|
| 每日采集主管道 | **wvb-cc-radar 的 fetch.py 分层查询模型** | T1/T2/T3 三层查询防漏、8 分类 ×100 仓库、JSON schema 完整、增量指标（24h/7d delta）、NEW 徽标 | 把韩语翻译换成中文；分类从 Claude Code 生态泛化到我们的生态域；增加配置化分类 |
| 多源聚合补充 | **agents-radar 的多源架构**（GitHub+ArXiv+HN+HF+PH…） | 10 源聚合 + LLM 摘要 + MCP 检索服务 | 抽取其数据源适配器；复用其 manifest 索引模式 |
| 数据源 API | **huchenme/github-trending-api** | 现成的 trending JSON API，免自建爬虫 | 直接调用，注意其维护停滞（2023）可自托管 |
| 增量去重范式 | **trending_archive 的 _short diff** | 只存新增，天然去重 | 迁移为"昨日快照对比"逻辑 |
| 全量冷启动 | **GH Archive** | 回填历史 10 年新仓库数据，建储备库底库 | 按日/周粒度聚合新增仓库，抽取元数据 |
| 中文质量池 | **GitHub-Chinese-Top-Charts / OpenGithubs** | 中文项目筛选 | 作为分类下的子池 |

### 4.2 参考（内容加工层，借鉴方法论）

| 用途 | 借鉴对象 | 借鉴点 |
|---|---|---|
| 内容策展质量 | HelloGitHub / GitHubDaily | 中文简介写法、语言/大分类索引组织 |
| 功能描述生成 | begin0808/github-hot | `features`（核心功能）+ `applications`（实用场景）双字段，正是"功能索引"的雏形，用 Gemini 生成 |
| 语义去重 | hunter-ai-content-factory | ChromaDB 语义去重逻辑 → 换成 LanceDB |
| 项目质量回溯 | ossinsight | 用历史事件数据验证"新项目是否真的在涨" |

### 4.3 储备库（自建，无现成可抄）

目标：**把所有每日新项目沉淀进 LanceDB，带功能索引 + 条件判断路由，留作长期储备**。详见第 5 节架构设计。

---

## 5. 储备库架构设计（LanceDB + 功能索引 + 条件判断）

### 5.1 总体数据流

```
┌─────────────── 每日采集（08:00 CST，GitHub Actions cron） ───────────────┐
│                                                                          │
│  数据源（多路并行）                                                        │
│   ├─ GitHub Trending 官方页（爬虫）                                        │
│   ├─ GitHub Search API（8 分类 × 多查询，wvb-cc-radar T1/T2/T3 模型）       │
│   ├─ agents-radar 式多源（ArXiv/HN/HF…，可选）                              │
│   ├─ OpenGithubs / 中文榜单（中文池）                                       │
│   └─ GH Archive（每周回填冷启动，可选）                                     │
│          │                                                                │
│          ▼                                                                │
│  ① 归一化 → 统一 Schema（full_name/desc/topics/lang/stars/deltas/created） │
│  ② 去重 → 与 LanceDB 已有记录按 full_name + 相似度去重（增量入库）            │
│  ③ 功能索引生成 → LLM 抽取：功能标签 + 一句话"它解决什么问题" + 适用场景       │
│  ④ 向量化 → embedding（full_name/desc/topics/功能标签/场景） → LanceDB       │
│          │                                                                │
│          ▼                                                                │
│  ⑤ 条件判断路由（详见 5.3）                                                 │
│   ├─ 命中「生态升级」→ 生成候选单 → PR 流程（人工/半自动确认后合入生态）        │
│   └─ 未命中 → 留在 LanceDB 储备库（可检索、可回溯）                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 5.2 LanceDB 表结构（统一 Schema）

```python
# repos 表（主表）
{
    "repo_id": "str",              # 唯一键 = full_name 的 hash
    "full_name": "str",            # owner/name
    "url": "str",
    "description": "str",          # 原始描述
    "language": "str",
    "topics": "list[str]",
    "stars": "int",
    "stars_delta_24h": "int",      # 24h 增量
    "stars_delta_7d": "int",       # 7d 增量
    "created_at": "str",           # 项目创建时间
    "first_seen_at": "str",        # 我们首次捕获时间
    "source": "list[str]",         # 来源（trending/search/hellogithub/...）
    # ↓↓↓ 功能索引（LLM 生成，核心差异化）↓↓↓
    "function_tags": "list[str]",  # 功能标签，如 ["RAG", "MCP", "vector-db", "translation"]
    "function_summary": "str",     # 一句话：它解决什么问题
    "use_case": "str",             # 适用场景
    "ecosystem_fit": "str",        # 与我们的生态匹配度分析（LLM）
    # ↓↓↓ 条件判断结果 ↓↓↓
    "category": "str",             # 生态升级 / 储备索引 / 忽略
    "decision_reason": "str",      # 判断依据
    "embedding": "vector[1024]",   # 向量列（LanceDB 原生支持）
}

# snapshots 表（每日快照，供趋势回溯）
{
    "date": "str",
    "repo_id": "str",
    "stars": "int",
    "rank": "int",                 # 当日榜单排名
    "is_new": "bool",              # 7 日内新建
}
```

### 5.3 条件判断机制（"什么时候用它"的决策规则）

采用 **分级打分 + 规则路由 + LLM 复核** 三层：

```python
def decide(repo) -> Decision:
    score = 0
    # ① 增长信号（数据驱动）
    if repo.stars_delta_24h >= 500:    score += 3   # 当日爆发
    if repo.stars_delta_7d >= 2000:    score += 3   # 一周走红
    if repo.is_new_this_week:          score += 1   # 新仓库
    if repo.stars >= 10000:            score += 1   # 稳定高星
    # ② 生态匹配信号（规则 + LLM）
    if match_ecosystem_keywords(repo): score += 2   # 命中生态关键词（MCP/agent/...）
    # ③ 质量信号
    if repo.license and repo.pushed_within_30d: score += 1  # 活跃且开源协议明确
    if not repo.archived:              score += 1

    if score >= 7 and ecosystem_match_score(repo) >= 0.8:
        return Decision("生态升级", reason=f"增长分{score}+生态匹配{...}")
    elif score >= 4:
        return Decision("储备索引", reason="有潜力但未达生态升级阈值，保留链接+功能索引")
    else:
        return Decision("忽略", reason="信号不足")
```

**关键点**：
- **生态升级路径**：`score≥7 且 生态匹配度≥0.8` → 生成候选 PR（含 function_tags / use_case / 对比分析），由人工或半自动确认后**合入生态**（对应"一部分直接处理当我们生态的升级"）。
- **储备索引路径**：`score≥4` → 保留链接 + 功能索引 + 条件标签，长期躺在 LanceDB（对应"一部分当索引目录保留链接和功能"）。
- **条件判断的复现形式**：LanceDB 支持 **全文检索 + 向量检索 + SQL 过滤**，未来任何时刻可按"什么时候需要什么功能"反查储备库：
  ```sql
  SELECT full_name, function_summary, use_case
  FROM repos
  WHERE category = '储备索引'
    AND function_tags LIKE '%MCP%'
  ORDER BY stars_delta_7d DESC
  ```
  或向量检索：`"我需要一个能压缩 LLM token 的开源库"` → 相似度 Top-K。

### 5.4 技术选型要点

| 组件 | 选型 | 理由 |
|---|---|---|
| 向量库 | **LanceDB**（嵌入式） | 无需单独服务、支持向量+全文混合检索、parquet 存储天然适合每日增量、与 Python/TypeScript 双 SDK |
| 采集调度 | GitHub Actions cron（每日 08:00） | 免费、与 CI 生态集成、失败可告警（参考 wvb-cc-radar 的 fetch-failure issue 自动上报） |
| LLM 加工 | Gemini 2.0 Flash / DeepSeek（便宜）+ 可降级 | 功能标签抽取、摘要、场景生成、匹配度分析；成本敏感 |
| Embedding | bge-m3 / text-embedding-3-small | 中文+英文混合，bge-m3 多语言效果好 |
| 检索入口 | MCP Server（借鉴 agents-radar） | 让生态内 Agent 直接可查储备库 |
| 快照回填 | GH Archive + DuckDB | 冷启动时回填历史数据，建立底库 |

---

## 6. 下一步行动建议

1. **本周**：搭建最小管道（GitHub Actions + wvb-cc-radar 式 fetch + LanceDB 入库），先跑通「每日采集 → 归一化 → 去重 → 入库」，数据量 100 条/日规模；
2. **下周**：接入 LLM 功能索引生成（function_tags / function_summary / use_case）与条件判断路由（生态升级/储备索引/忽略三分类）；
3. **第三周**：补全多源（agents-radar 适配 + 中文榜 + GH Archive 回填）、MCP 检索入口、生态升级候选 PR 半自动流程；
4. **持续**：每周用 ossinsight / GH Archive 回溯验证储备库中项目的真实增长，反向校准条件判断阈值。

---

## 7. 附录：候选项目完整清单

| 项目 | Star | License | 最后推送 | 数据源 | 更新频率 | 预处理 | 结构化 | 建议 |
|---|---|---|---|---|---|---|---|---|
| 521xueweihan/HelloGitHub | 169,406 | — | 2026-08 | 社区策展 | 月刊 | 语言分类+中文简介 | MD | 内容参照+历史语料 |
| GitHubDaily/GitHubDaily | 47,387 | — | 2025-12 | 人工策展 | 持续 | 12 大类索引 | MD | 内容参照 |
| vitalets/github-trending-repos | 2,988 | — | 2025-11 | Trending 爬虫 | 日/周 | 按语言订阅 | Issue | 参考 |
| PingCAP/ossinsight | 2,482 | Apache-2.0 | 2026-07 | GH 事件 | 实时 | 分析/LLM | 平台 | 质量回溯数据源 |
| ChHsiching/GitHub-Chinese-Top-Charts | 2,076 | — | 2025-10 | API | 周 | 语言分榜 | MD | 中文池 |
| OpenGithubs/github-monthly-rank | 1,473 | — | 2026-08 | API | 月 | 增长指标 | MD | 中文池+增量参照 |
| bonfy/github-trending | 1,081 | MIT | 2026-08 | Trending 爬虫 | 日 | 无 | MD | 参考 |
| duanyytop/agents-radar | 933 | MIT | 2026-08 | 10 源 | 日 | LLM 摘要+多语言+MCP | MD+JSON | **多源聚合改造** |
| huchenme/github-trending-api | 828 | MIT | 2023-01 | Trending 爬虫 | 请求时 | 无 | JSON API | **数据源 API** |
| kujian/githubTrending | 375 | — | 持续 | 自建爬虫 | 日 | 前端专题 | MD+Issue | 参考 |
| larsbijl/trending_archive | 394 | MIT | 2026-08 | Trending 爬虫 | 日 | **增量 diff** | MD | 去重范式 |
| Pangu-Immortal/hunter-ai-content-factory | 383 | MIT | 持续 | 多平台 | 手动/自动 | **ChromaDB 语义去重**+Gemini 写作 | SQLite+ChromaDB | 去重/写作思路迁移 |
| 521xueweihan/Hydra | 236 | — | 持续 | 多平台爬虫 | — | — | — | 采集实现参考 |
| begin0808/github-hot | 21 | MIT | 2026-08 | GitHub API | 周 | **Gemini features/applications** | JSON | **功能索引字段参照** |
| drwon-cmd/wvb-cc-radar | 4 | — | 2026-08 | Search API | 日 | **分层查询+增量+NEW+翻译+uses 标记** | JSON | **主管道改造基底** |

---

*本报告基于 2026-08-06 的源码级调研（15 个仓库 clone 实测），数据来源为各仓库 README、工作流配置与数据文件实测解析。*
