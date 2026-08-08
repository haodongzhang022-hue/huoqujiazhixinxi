"""huoqujiazhixinxi 开源项目储备管道 (wvb-cc-radar fetch 模型改造)。

模块:
  config          生态分类与 T1/T2/T3 分层查询配置
  github_client   GitHub API 客户端 (重试/退避/配额)
  fetch           每日采集主管道 (产出 data/snapshots/YYYY-MM-DD.json)

后续 (并行推进):
  preprocessor    真实抓取 → 归一化 → 去重
  classifier      打分模型 (增长信号+生态匹配+质量信号) → 三分类
  ingest          LanceDB 入库
"""

__version__ = "0.1.0"
