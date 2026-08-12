"""finance/catalog.py —— 数据源注册目录 (每个分类不同的获取方式)。

数据源 = 获取方式 (type) + 覆盖范围 (coverage) + 获取脚本 (script/module/command)
        + 调度策略 (schedule) + 渐进披露级别 (disclosure) + 数据落地 (storage)

索引到目标后: 除了数据本身, 还匹配到「获取信息的脚本」, 可触发获取或设置自动获取。

用法:
  python -m finance.catalog --list
  python -m finance.catalog --match --data-class crypto
  python -m finance.catalog --match --region CN --data-class futures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "finance" / "catalog.json"


class Catalog:
    """数据源目录 (从 config/finance/catalog.json 加载)。"""

    def __init__(self, data: dict):
        self.data = data
        self.sources: list[dict] = data.get("sources", [])
        self.by_id: dict[str, dict] = {s["id"]: s for s in self.sources}

    def get(self, sid: str) -> dict | None:
        return self.by_id.get(sid)

    def list_sources(self) -> list[dict]:
        return [{"id": s["id"], "name": s["name"], "type": s["type"],
                 "status": s.get("status", "unknown"), "script": s.get("script", "")}
                for s in self.sources]

    def match(self, data_class: str | None = None, region: str | None = None,
              exchange: str | None = None, trade_type: str | None = None,
              time_level: str | None = None) -> list[dict]:
        """按覆盖范围匹配数据源 (全部可选, 通配符 * 表示全量覆盖)。"""
        out = []
        for s in self.sources:
            cov = s.get("coverage", {})
            if data_class and data_class not in cov.get("data_classes", []) and "*" not in cov.get("data_classes", []):
                continue
            if region and region not in cov.get("regions", []) and "*" not in cov.get("regions", []):
                continue
            if exchange and exchange not in cov.get("exchanges", []) and "*" not in cov.get("exchanges", []):
                continue
            if trade_type and trade_type not in cov.get("trade_types", []) and "*" not in cov.get("trade_types", []):
                continue
            if time_level and time_level not in cov.get("time_levels", []) and "*" not in cov.get("time_levels", []):
                continue
            out.append(s)
        return out

    def sources_for_instrument(self, instrument: dict) -> list[dict]:
        """某品种 -> 可用的数据源 (按品种的 data_class/exchange/trade_types 匹配)。"""
        dc = instrument.get("data_class")
        ex = instrument.get("exchange")
        return self.match(data_class=dc, exchange=ex)

    def script_of(self, sid: str) -> dict | None:
        """数据源 -> 获取脚本信息 (script 文件 / module / command)。"""
        s = self.get(sid)
        if not s:
            return None
        return {
            "source": sid,
            "name": s.get("name"),
            "type": s.get("type"),
            "script": s.get("script"),
            "module": s.get("module"),
            "command": s.get("command"),
            "fetchers": s.get("fetchers", []),
            "requires": s.get("requires", {}),
        }

    def summary(self) -> dict:
        return {
            "sources": len(self.sources),
            "by_type": {t: len([s for s in self.sources if s.get("type") == t])
                        for t in {s.get("type") for s in self.sources}},
        }


def load_catalog(path: str | Path | None = None) -> Catalog:
    p = Path(path) if path else CATALOG_PATH
    with open(p, encoding="utf-8") as f:
        return Catalog(json.load(f))


def main():
    ap = argparse.ArgumentParser(description="数据源注册目录")
    ap.add_argument("--list", action="store_true", help="列出所有数据源")
    ap.add_argument("--match", action="store_true", help="按覆盖范围匹配数据源")
    ap.add_argument("--data-class", help="数据类别")
    ap.add_argument("--region", help="国家/地区")
    ap.add_argument("--exchange", help="交易所")
    ap.add_argument("--trade-type", help="交易类型")
    ap.add_argument("--time-level", help="时间级别")
    ap.add_argument("--script", metavar="SOURCE_ID", help="查看某数据源的获取脚本")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    cat = load_catalog()
    if args.script:
        info = cat.script_of(args.script)
        print(json.dumps(info, ensure_ascii=False, indent=2) if info else f"未找到数据源: {args.script}")
        return
    if args.match:
        result = cat.match(data_class=args.data_class, region=args.region, exchange=args.exchange,
                           trade_type=args.trade_type, time_level=args.time_level)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for s in result:
                print(f"  {s['id']:<16} {s['name']}  [{s['type']}]  ->  {s['script']}")
        return
    if args.json:
        print(json.dumps(cat.summary(), ensure_ascii=False, indent=2))
    else:
        for s in cat.list_sources():
            print(f"  {s['id']:<16} {s['name']}  [{s['type']}]  status={s['status']}")
        print(json.dumps(cat.summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
