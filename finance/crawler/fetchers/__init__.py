"""finance/crawler/fetchers —— 分渠道获取脚本 (每个渠道一个模块)。

设计 (对齐 Issue #6 解耦要求):
  - 每个渠道一个模块, 复用 finance.crawler.base 通用引擎;
  - 渠道的 地址/列定义/参数/存储 全部来自 LanceDB (channels/column_defs/params 表);
  - 模块只负责 "渠道特有" 的解析逻辑 (parse), 其余走通用流程;
  - 命名: {channel_id 下划线化}_fetcher.py, 必须暴露 `fetch(store, payload) -> dict`。

约定 fetch(store, payload) 返回:
  {
    "ok": bool, "rows": int, "records": [标准行...], "raw_rows": [原始行...],
    "error": str|None, "channel_id": ..., "instrument_id": ...
  }
"""

FETCHER_MODULES = [
    "finance.crawler.fetchers.cnb_sitemap_fetcher",
    "finance.crawler.fetchers.rss_fetcher",
    "finance.crawler.fetchers.akshare_fetcher",
    "finance.crawler.fetchers.yfinance_fetcher",
    "finance.crawler.fetchers.ccxt_fetcher",
    "finance.crawler.fetchers.fred_fetcher",
    "finance.crawler.fetchers.finnhub_fetcher",
    "finance.crawler.fetchers.alpha_vantage_fetcher",
    "finance.crawler.fetchers.manual_fetcher",
]

# 渠道 id -> 模块名 (也可从 channels 表 module 字段读取, 这里是内置映射兜底)
CHANNEL_TO_MODULE = {
    "cnb-sitemap": "finance.crawler.fetchers.cnb_sitemap_fetcher",
    "rss_news": "finance.crawler.fetchers.rss_fetcher",
    "akshare": "finance.crawler.fetchers.akshare_fetcher",
    "yfinance": "finance.crawler.fetchers.yfinance_fetcher",
    "ccxt": "finance.crawler.fetchers.ccxt_fetcher",
    "fred": "finance.crawler.fetchers.fred_fetcher",
    "finnhub": "finance.crawler.fetchers.finnhub_fetcher",
    "alpha_vantage": "finance.crawler.fetchers.alpha_vantage_fetcher",
    "manual": "finance.crawler.fetchers.manual_fetcher",
}


def get_fetcher(channel_id: str):
    """按渠道 id 加载 fetcher 模块 (优先 channels 表 module, 兜底内置映射)。"""
    import importlib

    from finance.lance.store import get_store

    store = get_store()
    ch = store.get("channels", "channel_id", channel_id)
    module = None
    if ch:
        module = ch.get("module")
    if not module:
        module = CHANNEL_TO_MODULE.get(channel_id)
    if not module:
        return None
    # 旧路径 finance.fetchers.* (旧版签名 fetch(payload)) -> 新路径 finance.crawler.fetchers.* (fetch(store, payload))
    if module.startswith("finance.fetchers."):
        module = "finance.crawler.fetchers." + module[len("finance.fetchers."):]
    try:
        mod = importlib.import_module(module)
        return getattr(mod, "fetch", None)
    except Exception:
        return None
