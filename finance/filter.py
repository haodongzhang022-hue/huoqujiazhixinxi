"""finance/filter.py —— 筛选器: 任意维度组合 -> 定位品种 + 匹配数据源 + 渐进披露路径。

筛选维度 (全部可选, 可自由组合):
  data_class   数据类别 (stock/futures/forex/crypto/macro/sentiment/...)
  region       国家/地区 (CN/US/HK/...)
  exchange     交易所/市场 (SSE/CME/BINANCE/...)
  instrument   品种名/代码 (CN.RB / AAPL / 600000 / BTC ...)
  time_level   时间级别 (1m/1h/1d/...)
  trade_type   交易类型 (spot/contract/perpetual/option/...)
  source       指定数据源 (akshare/yfinance/ccxt/fred/...)

输出: 匹配品种列表 + 每个品种可用的数据源 + 数据源获取脚本 + 调度信息。

用法:
  python -m finance.filter --data-class futures --region CN
  python -m finance.filter --region US --trade-type option
  python -m finance.filter --instrument BTC
  python -m finance.filter --data-class crypto --exchange BINANCE --json
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from finance.taxonomy import Taxonomy, load_taxonomy
from finance.catalog import Catalog, load_catalog


def filter_instruments(tax: Taxonomy, catalog: Catalog,
                       data_class: str | None = None, region: str | None = None,
                       exchange: str | None = None, trade_type: str | None = None,
                       instrument: str | None = None, time_level: str | None = None,
                       source: str | None = None) -> list[dict]:
    """六维筛选: 返回每个匹配品种 + 可用数据源 + 脚本 + 披露级别 + 调度。

    instrument 可以是: 品种 id (CN.RB) / 代码 (RB) / 名称 (螺纹钢) / 交易所符号 (600000)。
    """
    tax_instruments = tax.instruments_of(data_class=data_class, region=region,
                                         exchange=exchange, trade_type=trade_type)
    # 品种名/代码解析
    if instrument:
        resolved = tax.resolve_instrument(instrument, data_class=data_class, exchange=exchange)
        if resolved:
            tax_instruments = [resolved]
        else:
            # 名称/代码子串匹配
            q = instrument.strip().lower()
            tax_instruments = [i for i in tax_instruments
                               if q in i.get("id", "").lower()
                               or q in str(i.get("symbol", "")).lower()
                               or q in i.get("name", "").lower()]

    results: list[dict] = []
    for inst in tax_instruments:
        iid = inst.get("id") or inst.get("instrument_id")
        card = tax.describe_instrument(iid)
        # 匹配数据源: 先按品种覆盖, 再叠加 time_level/source 过滤
        sources = catalog.sources_for_instrument(inst)
        if time_level:
            sources = [s for s in sources if time_level in s.get("coverage", {}).get("time_levels", [])
                       or "*" in s.get("coverage", {}).get("time_levels", [])]
        if source:
            sources = [s for s in sources if s["id"] == source]
        results.append({
            "instrument": card or inst,
            "sources": [{
                "id": s["id"],
                "name": s["name"],
                "type": s["type"],
                "status": s.get("status", "unknown"),
                "script": s.get("script"),
                "module": s.get("module"),
                "command": s.get("command"),
                "schedule": s.get("schedule", {}),
                "disclosure": s.get("disclosure", {}),
                "storage": s.get("storage", {}),
                "requires": s.get("requires", {}),
                "fetchers": s.get("fetchers", []),
            } for s in sources],
        })
    return results


def match_summary(result: list[dict]) -> dict:
    """筛选结果摘要 (聚类统计: 按数据类别/国家/交易所/数据源)。"""
    from collections import Counter
    dc_counter, region_counter, ex_counter, src_counter = Counter(), Counter(), Counter(), Counter()
    total_sources = 0
    for r in result:
        inst = r.get("instrument", {})
        inst_id = inst.get("instrument", {}).get("id") or inst.get("id")
        d = inst.get("data_class", {}) or {}
        ex = inst.get("exchange", {}) or {}
        rg = inst.get("region", {}) or {}
        dc = d.get("id") if isinstance(d, dict) else d
        exid = ex.get("id") if isinstance(ex, dict) else ex
        rgid = rg.get("id") if isinstance(rg, dict) else rg
        if dc:
            dc_counter[dc] += 1
        if exid:
            ex_counter[exid] += 1
        if rgid:
            region_counter[rgid] += 1
        for s in r.get("sources", []):
            src_counter[s["id"]] += 1
            total_sources += 1
    return {
        "matched_instruments": len(result),
        "total_source_hits": total_sources,
        "by_data_class": dict(dc_counter),
        "by_region": dict(region_counter),
        "by_exchange": dict(ex_counter),
        "by_source": dict(src_counter),
    }


def main():
    ap = argparse.ArgumentParser(description="全球金融数据筛选器 (六维索引)")
    ap.add_argument("--data-class", help="数据类别")
    ap.add_argument("--region", help="国家/地区")
    ap.add_argument("--exchange", help="交易所")
    ap.add_argument("--trade-type", help="交易类型")
    ap.add_argument("--instrument", help="品种名/代码")
    ap.add_argument("--time-level", help="时间级别")
    ap.add_argument("--source", help="指定数据源")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--summary", action="store_true", help="只输出聚类统计摘要")
    args = ap.parse_args()

    tax = load_taxonomy()
    cat = load_catalog()
    result = filter_instruments(tax, cat, data_class=args.data_class, region=args.region,
                                exchange=args.exchange, trade_type=args.trade_type,
                                instrument=args.instrument, time_level=args.time_level,
                                source=args.source)
    if args.summary:
        print(json.dumps(match_summary(result), ensure_ascii=False, indent=2))
        return
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not result:
        print("未匹配到任何品种, 试试放宽筛选条件")
        return
    for r in result:
        inst = r.get("instrument", {})
        d = inst.get("data_class", {})
        ex = inst.get("exchange", {})
        rg = inst.get("region", {})
        inst_id = inst.get("instrument", {}).get("id") or inst.get("id")
        name = inst.get("instrument", {}).get("name") or inst.get("name")
        print(f"\n◆ {inst_id}  {name}  [{d.get('name') if isinstance(d, dict) else ''} | "
              f"{rg.get('name') if isinstance(rg, dict) else ''} | "
              f"{ex.get('name') if isinstance(ex, dict) else ''}]")
        print(f"  交易类型: {', '.join(str(t.get('name') if isinstance(t, dict) else t) for t in inst.get('trade_types', []))}")
        for s in r.get("sources", []):
            print(f"  - 数据源 [{s['id']}] {s['name']} ({s['type']}) status={s['status']}")
            print(f"    脚本: {s['script']}")
            print(f"    命令: {s['command']}")
            print(f"    调度: {json.dumps(s.get('schedule', {}), ensure_ascii=False)}")
    print()
    print(json.dumps(match_summary(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
