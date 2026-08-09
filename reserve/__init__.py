"""reserve 储备库管道包。

模块:
  store        LanceDB 存储层 (repo_reserve / repo_snapshots / needs)
  preprocessor 快照归一化 + 去重
  classifier   条件判断三分类 + 功能索引
  embedding    向量化 (本地 TF-hash / API)
  llm          LLM Provider 抽象层 (OpenAI 兼容 API / 本地 Ollama / 自定义端点)
  enrich       LLM 功能索引生成 (读 README/发布者介绍 -> function_tags/summary/use_case)
  review       LLM 代码审核 (action 候选四维评审) + 人工审核队列 (@CodeBuddy)
  cluster      能力聚类 (按功能标签 / 向量 K-means, 能力簇视图)
  quality      内容质量评估 (快照/储备库/趋势 + 每日质量报告)
  self_heal    管道自愈合 (健康检查 -> 诊断 -> 自动修复 -> 事件日志)
  dashboard    内容结构化整理视图 (总览/列表/能力簇/质量/快照/需求/审核)
  schemas      统一信息条目/数据源/信息流 数据契约 (Pydantic)
  feed         人类优先 / AI 优先 信息流 (对外公开, 一次获取多人共享)
  fastapi_app  FastAPI 聚合管理页面 + 对外信息流 API + 兼容既有 REST
  relations    二次整理层 (ISSUE #7): 金融各市场/品种间两两关联量化 + 预测 vs 实际对比
                (dims 维度 / frame 矩阵 / engine 评估引擎 / compare 预测验证 /
                 store 持久化 / schemas 契约 / demo 演示)
  ingest       fetch -> classify -> embed -> 入库 端到端管道
  search       全文/向量/混合检索
  trigger      条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)
  api          (旧) http.server REST API + Web 静态托管 (兼容保留)

快速开始:
  # 1. 采集 (真实 GitHub API)
  python -m pipeline.fetch --limit 5

  # 2. 入库 (归一化 -> 去重 -> 分类 -> LLM 增强/审核 -> 向量化 -> LanceDB)
  python -m reserve.ingest

  # 3. FastAPI 聚合管理 + 对外信息流 (推荐)
  python -m reserve.fastapi_app --port 8000
  #    浏览器: http://127.0.0.1:8000/
  #    对外信息流: GET /api/v1/feed?mode=human|ai

  # 4. 检索
  python -m reserve.search "需要 RAG 向量检索能力"

  # 5. 条件触发
  python -m reserve.trigger "MCP agent 智能体工具"

  # 6. 配置自定义 LLM (API 或本地 Ollama)
  cp config/llm.json.example config/llm.json  # 或环境变量

  # 7. 查看人工审核队列
  python -m reserve.review queue

  # 8. 质量评估 / 自愈合
  python -m reserve.quality --report
  python -m reserve.self_heal
"""

__version__ = "0.6.0"
