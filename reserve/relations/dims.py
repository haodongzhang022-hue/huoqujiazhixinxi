"""维度定义与解析 —— 把「市场/国家/品种/交易类型/时间级别」组织成**分层漏斗**。

ISSUE #7 的核心是「不同小目录下的两两关联」，但更重要的是：这套分类**必须是分层的**，
而不是把六个维度拍扁成一个平铺 key。原因：

1. 业务上是「多级条件筛选的漏斗」——从资产大类一路过滤到品种/时间级别，
   每一级是一个**功能域 (functional domain)**，有明确的父子/层级关系。
2. 后续模型要分别学习 **层内关系 (intra-layer)** 与 **层间关系 (inter-layer)**：
   - 层内：同一功能域里不同子项之间的联动（如同交易所下不同品种、同品种不同时间级别）；
   - 层间：不同功能域之间的传导（如宏观利率 → 权益市场、交易所 → 品种）。
   如果把六维拍平，层内/层间关系就混在一起无法区分了。

因此本模块在兼容旧 6 字段 Dim 的同时，显式声明 **LAYERS**（功能域分层漏斗），
并提供「层级归属 / 父子路径 / 层内 vs 层间判定」能力，供网络拓扑与模型使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# 功能域分层漏斗 (LAYERS)
#
# 从漏斗口（最粗、最上层）到漏斗底（最细、最底层），每一层是一个功能域。
# 每个功能域都有:
#   id        : 英文标识
#   name      : 中文功能域名
#   order     : 漏斗深度 (0 为最顶层, 值越大越靠底层)
#   dim_field : 对应 Dim 上的字段名
# ---------------------------------------------------------------------------
LAYERS: list[dict] = [
    {"id": "data_class", "name": "资产大类/功能域", "order": 0, "dim_field": "market",
     "label": "资产大类"},
    {"id": "region",     "name": "地区/国家",       "order": 1, "dim_field": "country",
     "label": "地区"},
    {"id": "exchange",   "name": "交易所/市场",     "order": 2, "dim_field": "exchange",
     "label": "交易所"},
    {"id": "instrument", "name": "品种/标的",       "order": 3, "dim_field": "symbol",
     "label": "品种"},
    {"id": "trade_type", "name": "交易类型",        "order": 4, "dim_field": "asset",
     "label": "交易类型"},
    {"id": "time_level", "name": "时间级别",        "order": 5, "dim_field": "timeframe",
     "label": "时间级别"},
]

# 字段 -> 层级 反向映射
_LAYER_BY_FIELD = {ly["dim_field"]: ly for ly in LAYERS}
# 按漏斗深度升序
_LAYERS_BY_ORDER = sorted(LAYERS, key=lambda ly: ly["order"])


def layers() -> list[dict]:
    """返回功能域分层漏斗定义 (按深度升序)。"""
    return [dict(ly) for ly in _LAYERS_BY_ORDER]


def layer_of_field(field: str) -> Optional[dict]:
    """给定 Dim 字段名, 返回其所属功能域层级。"""
    ly = _LAYER_BY_FIELD.get(field)
    return dict(ly) if ly else None


def funnel_depth(field: str) -> int:
    """给定 Dim 字段名, 返回漏斗深度 (顶层=0)。"""
    ly = _LAYER_BY_FIELD.get(field)
    return ly["order"] if ly else -1


MARKETS = ["equity", "futures", "forex", "crypto", "macro", "bond", "commodity", "sentiment"]
ASSETS = ["spot", "futures", "option", "index", "etf", "cash", "rate", "bond", "derivative", "*"]
TIMEFRAMES = ["tick", "1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M", "*"]

# 字段在漏斗中的展示顺序 (与 LAYERS 对齐)
_FIELD_ORDER = ["market", "country", "exchange", "symbol", "asset", "timeframe"]


@dataclass(frozen=True)
class Dim:
    """一个「小目录」的规范化维度表示。

    兼容旧版 6 字段 (market/country/exchange/symbol/asset/timeframe)，每个字段
    对应一个功能域层级 (见 LAYERS)。通过 `layers` / `path` 可拿到分层信息。
    """

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

    # ------------------------------------------------------------------
    # 分层漏斗能力
    # ------------------------------------------------------------------
    def active_layers(self) -> list[dict]:
        """返回该维度**已指定（非通配符）**的功能域层级，按漏斗深度升序。"""
        out = []
        for ly in _LAYERS_BY_ORDER:
            val = getattr(self, ly["dim_field"])
            if val and val != "*":
                item = dict(ly)
                item["value"] = val
                out.append(item)
        return out

    def layer_value(self, field: str) -> Optional[str]:
        """取某功能域字段在该维度上的具体值 (未指定则 None)。"""
        v = getattr(self, field)
        return v if v and v != "*" else None

    def path(self) -> list[str]:
        """漏斗路径：从最顶层到最底层的"指定字段:值"链，用于展示分层归属。"""
        return [f"{ly['label']}:{getattr(self, ly['dim_field'])}"
                for ly in _LAYERS_BY_ORDER
                if getattr(self, ly["dim_field"]) not in ("", "*")]

    def funnel_label(self) -> str:
        """分层漏斗展示标签，如「资产大类:期货 → 地区:CN → 交易所:SHFE → 品种:CU」。"""
        p = self.path()
        return " → ".join(p) if p else "*"

    def shared_layers(self, other: "Dim") -> list[dict]:
        """与另一维度在**同一功能域层级**上值相同（含通配符视为不限）的层级。"""
        shared = []
        for ly in _LAYERS_BY_ORDER:
            a = getattr(self, ly["dim_field"])
            b = getattr(other, ly["dim_field"])
            if a == "*" or b == "*" or a == b:
                shared.append(dict(ly))
        return shared

    def diff_layers(self, other: "Dim") -> list[dict]:
        """与另一维度在**不同功能域层级**上值不同的层级（用于层间关系判定）。"""
        diff = []
        for ly in _LAYERS_BY_ORDER:
            a = getattr(self, ly["dim_field"])
            b = getattr(other, ly["dim_field"])
            if a != "*" and b != "*" and a != b:
                diff.append(dict(ly))
        return diff


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


def relationship_kind(a: Dim, b: Dim) -> dict:
    """判定 A→B 两个维度的关系类型（层内 vs 层间）。

    返回:
      {
        "kind": "intra_layer" | "inter_layer" | "same_node",
        "shared_layers": [...],   # 值相同(含通配)的功能域层级
        "diff_layers": [...],     # 值不同的功能域层级
        "diff_fields": [...],     # 发生不同的字段名
      }
    判定规则（对齐业务语义——功能域漏斗）:
      - 若所有非通配字段值都相同 (a == b) -> same_node (自环, 一般排除)
      - **层内 intra_layer**: 两个维度属于**同一个最顶层功能域**（资产大类
        data_class / market 相同），仅在最细分/子分类层（品种/交易类型/时间级别，
        乃至同大类下的不同地区/交易所）上不同。例如同品种不同交易类型
        (000300.index ↔ 000300.etf)、同品种不同时间级别 (BTC.4h ↔ BTC.1d)。
        模型学的是「同一功能域分支内部的联动」。
      - **层间 inter_layer**: 两个维度属于**不同的最顶层功能域**（资产大类不同，
        如股票 ↔ 期货、宏观 ↔ 加密），跨功能域传导。例如美债利率 → 股票、
        CU 期货 → 外汇。模型学的是「跨功能域的层间传导」。
    """
    # 兼容 dict/str 入参：统一转成 Dim
    if not isinstance(a, Dim):
        a = parse_dim(a)
    if not isinstance(b, Dim):
        b = parse_dim(b)
    if a == b:
        return {"kind": "same_node", "shared_layers": a.shared_layers(b),
                "diff_layers": [], "diff_fields": []}
    shared = a.shared_layers(b)
    diff = a.diff_layers(b)
    # 找出发生不同的字段（按漏斗深度升序，最靠漏斗口的一个作为分界）
    diff_fields = []
    for ly in _LAYERS_BY_ORDER:
        f = ly["dim_field"]
        va, vb = getattr(a, f), getattr(b, f)
        if va != "*" and vb != "*" and va != vb:
            diff_fields.append(f)
    # 分界层 = 最靠漏斗口（最粗、最上层）发生不同的那一层
    boundary_field = diff_fields[0] if diff_fields else None
    boundary_layer = _LAYER_BY_FIELD.get(boundary_field) if boundary_field else None
    if not boundary_field:
        # 没有任何字段取值不同 -> 层内（同分支不同子项，如通配导致的差异）
        return {"kind": "intra_layer", "shared_layers": shared, "diff_layers": diff,
                "diff_fields": diff_fields, "boundary_layer": boundary_layer,
                "boundary_order": boundary_layer["order"] if boundary_layer else -1}
    # 若分界发生在最顶层功能域(资产大类 market) -> 层间 (跨功能域传导)
    if boundary_layer["dim_field"] == "market":
        kind = "inter_layer"
    else:
        kind = "intra_layer"
    return {"kind": kind, "shared_layers": shared, "diff_layers": diff,
            "diff_fields": diff_fields, "boundary_layer": boundary_layer,
            "boundary_order": boundary_layer["order"] if boundary_layer else -1}
