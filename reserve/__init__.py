"""reserve 储备库管道包。

模块:
  store        LanceDB 存储层 (repo_reserve / repo_snapshots / needs)
  preprocessor 快照归一化 + 去重
  classifier   条件判断三分类 + 功能索引
  embedding    向量化 (本地 TF-hash / API)
  llm          LLM Provider 抽象层 (OpenAI 兼容 API / 本地 Ollama / 自定义端点)
  enrich       LLM 功能索引生成 (读 README/发布者介绍 -> function_tags/summary/use_case)
  review       LLM 代码审核 (action 候选四维评审) + 人工审核队列 (@CodeBuddy)
  ingest       fetch -> classify -> embed -> 入库 端到端管道
  search       全文/向量/混合检索
  trigger      条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)
  api          REST API (含 /api/v1/llm/status + /api/v1/review/* 审核端点)

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
"""

__version__ = "0.4.0"
