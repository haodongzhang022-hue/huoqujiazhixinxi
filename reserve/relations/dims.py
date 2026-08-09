"""维度定义与解析 —— 把「市场/国家/品种/交易类型/时间级别」统一为目录 key。

ISSUE #7 的核心是「不同小目录下的两两关联」。数据获取层 (ISSUE #6) 把全球金融数据
按「国家 → 交易所 → 品种 → 交易类型 → 时间级别」组织成目录树；本模块负责把一条
行情数据/品种解析成唯一的 **dimension key**，作为关联矩阵的行列坐标。

维度规范:
  market     : 市场类型: equity(股票) / futures(期货) / forex(外汇) / crypto(区块链/加密)
               / macro(宏观) / bond(债券) / commodity(大宗商品) / sentiment(舆论/情绪)
  country    : 国家/地区: CN / US / EU / JP / HK / GB / SG / KR / global(跨境/宏观) ...
  exchange   : 交易所: SSE / SZSE / HKEX / NYSE / NASDAQ / CME / SHFE / DCE / CZCE / INE / FX / CRYPTO ...
  symbol     : 品种名: 000300 / AAPL / BTC / USDCNY / CU / rb / GC ...
  asset      : 交易类型: spot(现货) / futures(合约/期货) / option(期权) / index(指数)
               / etf(ETF) / cash(汇率现金) / rate(利率) / bond ...
  timeframe  : 时间级别: tick / 1m / 5m / 15m / 1h / 4h / 1d / 1w / 1M

每个维度可缺省 (用 "*" 表示“任意/该维度不参与区分”)，解析规则:
  "futures.CU.CN.SHFE.1d"   -> 全维度
  "futures.CU"              -> 缺省部分自动补 "*"
"""

from __future__ import annotations

from dataclasses import dataclass, field

MARKETS = ["equity", "futures", "forex", "crypto", "macro", "bond", "commodity", "sentiment"]
ASSETS = ["spot", "futures", "option", "index", "etf", "cash", "rate", "bond", "derivative", "*"]
TIMEFRAMES = ["tick", "1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M", "*"]


@dataclass(frozen=True)
class Dim:
    """一个「小目录」的规范化维度表示。"""

    market: str = "*"
    country: str = "*"
    exchange: str = "*"
    symbol: str = "*"
    asset: str = "*"
    timeframe: str = "*"

    def __str__(self) -> str:
        return f"{self.market}.{self.country}.{self.exchange}.{self.symbol}.{self.asset}.{self.timeframe}"

    @property
    def key(self) -> str:
        return str(self)

    @property
    def short(self) -> str:
        """人类可读短名。"""
        parts = []
        if self.symbol != "*":
            parts.append(self.symbol)
        if self.market != "*":
            parts.append(self.market)
        if self.country != "*":
            parts.append(self.country)
        if self.exchange != "*":
            parts.append(self.exchange)
        if self.asset != "*":
            parts.append(self.asset)
        if self.timeframe != "*":
            parts.append(self.timeframe)
        return ".".join(parts) if parts else "*"

    def to_dict(self) -> dict:
        return {"market": self.market, "country": self.country, "exchange": self.exchange,
                "symbol": self.symbol, "asset": self.asset, "timeframe": self.timeframe}

    def matches(self, other: "Dim") -> bool:
        """是否属于同一个「目录」（通配符匹配任意值）。"""
        return all(a == "*" or b == "*" or a == b
                   for a, b in zip(self.to_dict().values(), other.to_dict().values()))


def parse_dim(spec: str | dict | None) -> Dim:
    """把字符串/字典解析为 Dim。

    支持:
      "futures.CU.CN.SHFE.1d"            -> 6 段全维度
      "futures.CU"                       -> 缺省补 "*"
      {"market": "forex", "symbol": "EURUSD"} -> 字典
    """
    if spec is None or spec == "" or spec == "*":
        return Dim()
    if isinstance(spec, dict):
        return Dim(market=str(spec.get("market", "*") or "*"),
                   country=str(spec.get("country", "*") or "*"),
                   exchange=str(spec.get("exchange", "*") or "*"),
                   symbol=str(spec.get("symbol", "*") or "*"),
                   asset=str(spec.get("asset", "*") or "*"),
                   timeframe=str(spec.get("timeframe", "*") or "*"))
    parts = [p.strip() for p in str(spec).split(".")]
    parts = [p for p in parts if p]
    # 位置式: market.country.exchange.symbol.asset.timeframe
    # 短格式智能映射: "futures.CU" / "BTC" 这类 1-2 段按 (market, symbol) 解释
    if len(parts) == 1:
        parts = [parts[0], "*"]
    if len(parts) == 2:
        parts = [parts[0], "*", "*", parts[1], "*", "*"]
    if len(parts) > 6:
        parts = parts[:6]
    while len(parts) < 6:
        parts.append("*")
    return Dim(market=parts[0], country=parts[1], exchange=parts[2],
               symbol=parts[3], asset=parts[4], timeframe=parts[5])


def dim_label(d: Dim) -> str:
    """用于展示的标签，例如: 期货.CU(沪铜).CN.SHFE.日线。"""
    market_label = {
        "equity": "股票", "futures": "期货", "forex": "外汇", "crypto": "加密",
        "macro": "宏观", "bond": "债券", "commodity": "大宗", "sentiment": "舆情",
    }.get(d.market, d.market)
    asset_label = {"spot": "现货", "futures": "合约", "option": "期权", "index": "指数",
                   "etf": "ETF", "cash": "现金", "rate": "利率", "bond": "债券",
                   "derivative": "衍生", "*": ""}.get(d.asset, d.asset)
    tf_label = {"1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "1h": "1小时",
                "4h": "4小时", "1d": "日线", "1w": "周线", "1M": "月线",
                "tick": "Tick", "*": ""}.get(d.timeframe, d.timeframe)
    parts = []
    if d.symbol != "*":
        parts.append(d.symbol)
    if d.market != "*":
        parts.append(market_label)
    if d.country != "*":
        parts.append(d.country)
    if d.exchange != "*":
        parts.append(d.exchange)
    if d.asset != "*":
        parts.append(asset_label)
    if d.timeframe != "*":
        parts.append(tf_label)
    return "·".join(p for p in parts if p) or "*"
