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
  ingest       fetch -> classify -> embed -> 入库 端到端管道
  search       全文/向量/混合检索
  trigger      条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)
  api          REST API (含 /api/v1/llm/status + /api/v1/review/* + /api/v1/quality
               + /api/v1/health|heal + /api/v1/dashboard/* + Web 页面托管)

快速开始:
  # 1. 采集 (真实 GitHub API)
  python -m pipeline.fetch --limit 5

  # 2. 入库 (归一化 -> 去重 -> 分类 -> LLM 增强/审核 -> 向量化 -> LanceDB)
  python -m reserve.ingest

  # 3. 检索
  python -m reserve.search "需要 RAG 向量检索能力"

  # 4. 条件触发
  python -m reserve.trigger "MCP agent 智能体工具"

  # 5. 配置自定义 LLM (API 或本地 Ollama)
  cp config/llm.json.example config/llm.json  # 或直接编辑 config/llm.json
  # 或环境变量: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / OLLAMA_BASE_URL / OLLAMA_MODEL

  # 6. 查看人工审核队列 (LLM 审核后的 action 候选)
  python -m reserve.review queue

  # 7. 质量评估 (每天获取的内容质量)
  python -m reserve.quality --report

  # 8. 自愈合 (管道自动修复)
  python -m reserve.self_heal

  # 9. Web 管理台 + 展示 API
  python -m reserve.api --port 8000   # 浏览器打开 http://127.0.0.1:8000/
"""

__version__ = "0.5.0"
