"""finance/crawler —— 通用爬虫引擎 (通用模板 + 分渠道参数/定义文件, 解除耦合)。

分层设计 (对齐 Issue #6 需求):
  1. 通用部分 (本包): 与具体渠道无关
       base.py        爬虫基类: 请求/重试/限流/编码/分页 -> 原始行
       fields.py      标准字段映射: 渠道原始列 -> 标准字段 (读 column_defs 表)
       dispatcher.py  调度分发: 渠道 -> 获取器 -> 引擎 -> 标准行 -> 落库
  2. 渠道定义 (LanceDB channels 表): 数据地址/获取方式/获取脚本/存储位置
  3. 列定义   (LanceDB column_defs 表): 本渠道列名 -> 标准字段, 类型, 清洗规则
  4. 参数特征 (LanceDB params 表): 渠道/品种/获取器/请求/存储/调度 各级参数

每个渠道只需在 lance 库登记 3 类记录:
  - channels 表: 一条渠道定义 (address/method/script/storage)
  - column_defs 表: 若干条列映射 (原始列名 -> 标准字段)
  - params 表: 若干条参数/特征 (按 scope 分类)
通用引擎读取这三张表即可完成 "获取 -> 映射 -> 清洗 -> 落库" 全链路,
新渠道 = 新增定义 + (可选) 自定义 fetcher 模块, 无需改动通用代码。

子包:
  finance.crawler.fetchers/   分渠道获取脚本 (每渠道一个模块, 复用通用引擎)
"""

__version__ = "0.2.0"
