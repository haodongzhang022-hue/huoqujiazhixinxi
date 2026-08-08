"""reserve 储备库管道包。

模块:
  store        LanceDB 存储层 (repo_reserve / repo_snapshots / needs)
  preprocessor 快照归一化 + 去重
  classifier   条件判断三分类 + 功能索引
  embedding    向量化 (本地 TF-hash / API)
  ingest       fetch -> classify -> embed -> 入库 端到端管道
  search       全文/向量/混合检索
  trigger      条件触发引擎 (AUTO/SUGGEST/LOG + needs 双向生长回路)

快速开始:
  # 1. 采集 (真实 GitHub API)
  python -m pipeline.fetch --limit 5

  # 2. 入库 (归一化 -> 去重 -> 分类 -> 向量化 -> LanceDB)
  python -m reserve.ingest

  # 3. 检索
  python -m reserve.search "需要 RAG 向量检索能力"

  # 4. 条件触发
  python -m reserve.trigger "MCP agent 智能体工具"
"""

__version__ = "0.3.0"
