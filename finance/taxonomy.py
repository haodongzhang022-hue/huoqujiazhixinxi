"""finance/taxonomy.py —— 金融分类体系加载与查询 (六维索引)。

六维:
  1. data_class   数据类别/资产大类 (stock/futures/forex/crypto/macro/sentiment/bond/fund/realestate/commodity)
  2. region       国家/地区 (CN/HK/US/JP/KR/TW/SG/EU/UK/DE/FR/AU/GLOBAL)
  3. exchange     交易所/市场/权威机构 (SSE/SHFE/CME/BINANCE/FRED/NBS...)
  4. time_level   时间级别 (tick/1m/5m/.../1d/1w/1M/1Q/1Y)
  5. instrument   品种 (具体标的: 股票代码/期货品种/货币对/宏观指标...)
  6. trade_type   交易类型 (spot/contract/perpetual/option/forward/swap/cfd/etf/indices)

用法:
  python -m finance.taxonomy --stats
  python -m finance.taxonomy --exchanges CN
  python -m finance.taxonomy --instruments --data-class futures --region CN
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "finance" / "taxonomy.json"


class Taxonomy:
    """金融分类体系 (从 config/finance/taxonomy.json 加载)。"""

    def __init__(self, data: dict):
        self.data = data
        self.data_classes: dict[str, dict] = data.get("data_classes", {})
        self.regions: dict[str, dict] = data.get("regions", {})
        self.exchanges: dict[str, dict] = data.get("exchanges", {})
        self.time_levels: dict[str, dict] = data.get("time_levels", {})
        self.trade_types: dict[str, dict] = data.get("trade_types", {})
        self.instruments: dict[str, dict] = data.get("instruments", {})

    # ---------- 查询 ----------
    def get_data_class(self, dc: str) -> dict | None:
        return self.data_classes.get(dc)

    def get_region(self, r: str) -> dict | None:
        return self.regions.get(r)

    def get_exchange(self, ex: str) -> dict | None:
        return self.exchanges.get(ex)

    def get_time_level(self, tl: str) -> dict | None:
        return self.time_levels.get(tl)

    def get_trade_type(self, tt: str) -> dict | None:
        return self.trade_types.get(tt)

    def get_instrument(self, iid: str) -> dict | None:
        return self.instruments.get(iid)

    def exchanges_of_region(self, region: str) -> list[dict]:
        return [v for v in self.exchanges.values() if v.get("region") == region]

    def exchanges_of_class(self, dc: str) -> list[dict]:
        return [v for v in self.exchanges.values() if dc in v.get("data_classes", [])]

    def instruments_of(self, data_class: str | None = None, region: str | None = None,
                       exchange: str | None = None, trade_type: str | None = None) -> list[dict]:
        """按任意维度组合过滤品种 (全部可选)。"""
        out = []
        for iid, inst in self.instruments.items():
            if data_class and inst.get("data_class") != data_class:
                continue
            if exchange:
                ex = self.exchanges.get(inst.get("exchange"), {})
                if inst.get("exchange") != exchange and ex.get("id") != exchange:
                    continue
            if region:
                ex = self.exchanges.get(inst.get("exchange"), {})
                if ex.get("region") != region:
                    continue
            if trade_type and trade_type not in inst.get("trade_types", []):
                continue
            item = dict(inst)
            item["id"] = iid
            out.append(item)
        return out

    def resolve_instrument(self, symbol: str, data_class: str | None = None,
                           exchange: str | None = None) -> dict | None:
        """宽松解析品种: 优先 id 精确匹配, 再按 symbol+exchange 或 symbol 模糊匹配。"""
        if symbol in self.instruments:
            return {**self.instruments[symbol], "id": symbol}
        for iid, inst in self.instruments.items():
            if inst.get("symbol") == symbol and (not exchange or inst.get("exchange") == exchange):
                return {**inst, "id": iid}
        for iid, inst in self.instruments.items():
            if inst.get("symbol") == symbol and (not data_class or inst.get("data_class") == data_class):
                return {**inst, "id": iid}
        return None

    def exchange_names(self) -> list[str]:
        return list(self.exchanges.keys())

    def data_class_names(self) -> list[str]:
        return list(self.data_classes.keys())

    def stats(self) -> dict:
        return {
            "data_classes": len(self.data_classes),
            "regions": len(self.regions),
            "exchanges": len(self.exchanges),
            "time_levels": len(self.time_levels),
            "trade_types": len(self.trade_types),
            "instruments": len(self.instruments),
            "instruments_by_class": {
                dc: len(self.instruments_of(data_class=dc)) for dc in self.data_classes
            },
        }

    def describe_instrument(self, iid: str) -> dict | None:
        """品种 -> 完整索引卡 (品种 + 所属交易所 + 国家 + 数据类别 + 交易类型 + 时间级别)。"""
        inst = self.get_instrument(iid)
        if not inst:
            return None
        ex = self.get_exchange(inst.get("exchange", "")) or {}
        region = self.get_region(ex.get("region", "")) or {}
        return {
            "instrument": {**inst, "id": iid},
            "exchange": ex,
            "region": region,
            "data_class": self.get_data_class(inst.get("data_class", "")),
            "trade_types": [self.get_trade_type(t) for t in inst.get("trade_types", []) if self.get_trade_type(t)],
            "available_time_levels": self._time_levels_for(inst),
        }

    def _time_levels_for(self, inst: dict) -> list[dict]:
        dc = inst.get("data_class", "")
        base = ["1d", "1w", "1M"]
        if dc in ("stock", "futures", "crypto", "forex", "commodity", "bond", "fund"):
            base = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"]
        if dc in ("crypto",):
            base = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        if dc in ("macro", "realestate"):
            base = ["1d", "1w", "1M", "1Q", "1Y"]
        return [self.get_time_level(t) for t in base if self.get_time_level(t)]


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    p = Path(path) if path else TAXONOMY_PATH
    with open(p, encoding="utf-8") as f:
        return Taxonomy(json.load(f))


def main():
    ap = argparse.ArgumentParser(description="金融分类体系查询")
    ap.add_argument("--stats", action="store_true", help="分类统计")
    ap.add_argument("--exchanges", metavar="REGION", help="某国家/地区的交易所")
    ap.add_argument("--instruments", action="store_true", help="按维度筛选品种")
    ap.add_argument("--data-class", help="数据类别")
    ap.add_argument("--region", help="国家/地区")
    ap.add_argument("--exchange", help="交易所")
    ap.add_argument("--trade-type", help="交易类型")
    ap.add_argument("--describe", metavar="INSTRUMENT_ID", help="品种索引卡")
    args = ap.parse_args()

    tax = load_taxonomy()
    if args.describe:
        card = tax.describe_instrument(args.describe)
        print(json.dumps(card, ensure_ascii=False, indent=2) if card else f"未找到品种: {args.describe}")
        return
    if args.exchanges:
        for ex in tax.exchanges_of_region(args.exchanges):
            print(f"  {ex['id']:<10} {ex['name']}")
        return
    if args.instruments:
        for inst in tax.instruments_of(data_class=args.data_class, region=args.region,
                                       exchange=args.exchange, trade_type=args.trade_type):
            print(f"  {inst['id']:<22} {inst['name']:<14} {inst['symbol']:<10} @{inst['exchange']}")
        return
    print(json.dumps(tax.stats(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
