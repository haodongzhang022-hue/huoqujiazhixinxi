"""finance/fetchers/__init__.py —— 获取脚本注册。

每个数据源一个 *_fetcher.py 模块, 必须暴露 `fetch(payload: dict) -> dict`。
未安装对应依赖时抛异常, 由 finance/registry.py 自动降级 demo 模式。
"""

FETCHER_MODULES = [
    "finance.fetchers.akshare_fetcher",
    "finance.fetchers.yfinance_fetcher",
    "finance.fetchers.ccxt_fetcher",
    "finance.fetchers.fred_fetcher",
    "finance.fetchers.finnhub_fetcher",
    "finance.fetchers.rss_fetcher",
    "finance.fetchers.alpha_vantage_fetcher",
    "finance.fetchers.manual_fetcher",
]
