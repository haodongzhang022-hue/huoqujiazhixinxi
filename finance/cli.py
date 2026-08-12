"""finance/cli.py —— 金融数据超索引框架 CLI 统一入口。

子命令:
  search    筛选器: 六维组合定位品种 + 数据源 (等价 finance.filter)
  index     索引级披露 (L0)
  meta      元数据级披露 (L1)
  fetch     触发获取全量数据 (L2, 走 registry)
  schedule  调度: 增删查任务 / run-once / daemon (等价 finance.scheduler)
  catalog   数据源目录查询 (等价 finance.catalog)
  taxonomy  分类体系查询 (等价 finance.taxonomy)
  lance     LanceDB 统一管理: 渠道/列/参数/任务/数据/挖掘 (等价 finance.lance.cli)
  api       启动 REST API 服务

用法:
  python -m finance.cli search --data-class futures --region CN
  python -m finance.cli search --instrument BTC --json
  python -m finance.cli index --instrument CN.RB
  python -m finance.cli meta --instrument CN.RB
  python -m finance.cli fetch --instrument CN.RB --source akshare --time-level 1d
  python -m finance.cli schedule --add --instrument CRYPTO.BTC --source ccxt --every 5m
  python -m finance.cli schedule --list
  python -m finance.cli schedule --run-once
  python -m finance.cli catalog --match --data-class crypto
  python -m finance.cli taxonomy --stats
  python -m finance.cli lance init          # LanceDB 建表+种子初始化
  python -m finance.cli lance fetch --channel ccxt --instrument CRYPTO.BTC
  python -m finance.cli lance tasks --add --channel akshare --instrument CN.RB --every 1d
  python -m finance.cli lance discovery --run
  python -m finance.cli lance data --stats
"""

from __future__ import annotations

import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser(description="全球金融数据超索引框架 (Data Source Super Index)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ---- search / filter ----
    p = sub.add_parser("search", help="六维筛选器: 定位品种 + 数据源")
    p.add_argument("--data-class", help="数据类别")
    p.add_argument("--region", help="国家/地区")
    p.add_argument("--exchange", help="交易所")
    p.add_argument("--trade-type", help="交易类型")
    p.add_argument("--instrument", help="品种名/代码")
    p.add_argument("--time-level", help="时间级别")
    p.add_argument("--source", help="指定数据源")
    p.add_argument("--json", action="store_true")
    p.add_argument("--summary", action="store_true")

    # ---- index / meta / fetch (disclosure) ----
    for name, lvl in (("index", "index"), ("meta", "meta")):
        p = sub.add_parser(name, help=f"渐进式披露 {lvl.upper()} 级")
        p.add_argument("--instrument", required=True)
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("fetch", help="渐进式披露 FULL 级: 触发获取全量数据")
    p.add_argument("--instrument", required=True)
    p.add_argument("--source", help="数据源 id")
    p.add_argument("--time-level", help="时间级别")
    p.add_argument("--trade-type", help="交易类型")
    p.add_argument("--refresh", action="store_true", help="强制重新获取")
    p.add_argument("--force-demo", action="store_true")

    # ---- schedule ----
    p = sub.add_parser("schedule", help="调度器: 频率/时间/自动获取")
    p.add_argument("--add", action="store_true")
    p.add_argument("--instrument")
    p.add_argument("--source")
    p.add_argument("--time-level")
    p.add_argument("--trade-type")
    p.add_argument("--every", help="频率 5m/1h/1d")
    p.add_argument("--at", help="每天时刻 HH:MM")
    p.add_argument("--list", action="store_true")
    p.add_argument("--remove", metavar="TASK_ID")
    p.add_argument("--run-once", action="store_true")
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--scan-interval", type=float, default=30.0)

    # ---- catalog ----
    p = sub.add_parser("catalog", help="数据源目录")
    p.add_argument("--list", action="store_true")
    p.add_argument("--match", action="store_true")
    p.add_argument("--data-class")
    p.add_argument("--region")
    p.add_argument("--exchange")
    p.add_argument("--trade-type")
    p.add_argument("--time-level")
    p.add_argument("--script", metavar="SOURCE_ID")
    p.add_argument("--json", action="store_true")

    # ---- taxonomy ----
    p = sub.add_parser("taxonomy", help="分类体系")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--exchanges", metavar="REGION")
    p.add_argument("--instruments", action="store_true")
    p.add_argument("--data-class")
    p.add_argument("--region")
    p.add_argument("--exchange")
    p.add_argument("--trade-type")
    p.add_argument("--describe", metavar="INSTRUMENT_ID")

    # ---- api ----
    p = sub.add_parser("api", help="启动 REST API")
    p.add_argument("--port", type=int, default=8100)

    # ---- lance (LanceDB 统一管理) ----
    p = sub.add_parser("lance", help="LanceDB 统一管理: 渠道/列/参数/任务/数据/挖掘")
    p.add_argument("args", nargs=argparse.REMAINDER, help="转发给 finance.lance.cli 的参数")

    args = ap.parse_args()

    if args.cmd == "search":
        from finance.filter import filter_instruments, match_summary
        from finance.taxonomy import load_taxonomy
        from finance.catalog import load_catalog
        tax, cat = load_taxonomy(), load_catalog()
        result = filter_instruments(tax, cat, data_class=args.data_class, region=args.region,
                                    exchange=args.exchange, trade_type=args.trade_type,
                                    instrument=args.instrument, time_level=args.time_level,
                                    source=args.source)
        if args.summary:
            print(json.dumps(match_summary(result), ensure_ascii=False, indent=2))
        elif args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not result:
                print("未匹配到任何品种, 试试放宽筛选条件")
                return
            for r in result:
                inst = r.get("instrument", {})
                d, ex, rg = inst.get("data_class", {}), inst.get("exchange", {}), inst.get("region", {})
                iid = inst.get("instrument", {}).get("id") or inst.get("id")
                print(f"\n◆ {iid}  {inst.get('instrument', {}).get('name') or inst.get('name')}  "
                      f"[{d.get('name') if isinstance(d, dict) else ''} | "
                      f"{rg.get('name') if isinstance(rg, dict) else ''} | "
                      f"{ex.get('name') if isinstance(ex, dict) else ''}]")
                for s in r.get("sources", []):
                    print(f"  - [{s['id']}] {s['name']} ({s['type']}) 脚本={s['script']}")
                    print(f"    命令: {s['command']}")
            print()
            print(json.dumps(match_summary(result), ensure_ascii=False, indent=2))

    elif args.cmd == "index":
        from finance.disclosure import index_level
        r = index_level(args.instrument)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.cmd == "meta":
        from finance.disclosure import meta_level
        r = meta_level(args.instrument)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))

    elif args.cmd == "fetch":
        from finance.disclosure import full_level
        r = full_level(args.instrument, source=args.source, time_level=args.time_level,
                       trade_type=args.trade_type, refresh=args.refresh,
                       force_demo=args.force_demo)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))

    elif args.cmd == "schedule":
        from finance.scheduler import Scheduler
        sched = Scheduler()
        if args.add:
            if not args.instrument or not args.source:
                print("--add 需要 --instrument 和 --source", file=sys.stderr)
                sys.exit(1)
            t = sched.add(args.instrument, args.source, time_level=args.time_level,
                          trade_type=args.trade_type, every=args.every, at=args.at)
            print(json.dumps(t, ensure_ascii=False, indent=2))
        elif args.list:
            if not sched.tasks:
                print("(空)")
            for t in sched.tasks:
                print(f"  [{t['id']}] {t['instrument_id']} <- {t['source']} "
                      f"every={t.get('every') or '-'} at={t.get('at') or '-'} "
                      f"next={t.get('next_run') or 'manual'} status={t.get('status')} enabled={t.get('enabled')}")
        elif args.remove:
            print("已删除" if sched.remove(args.remove) else f"未找到任务 {args.remove}")
        elif args.run_once:
            results = sched.run_due()
            for r in results:
                t = r.get("task", {})
                print(f"  [{t.get('id')}] {t.get('instrument_id')} <- {t.get('source')}: "
                      f"{'OK' if r.get('ok') else 'ERROR ' + str(r.get('error', ''))}")
            print(f"本次触发 {len(results)} 个任务")
        elif args.daemon:
            sched.daemon(interval=args.scan_interval)
        else:
            print("schedule 子命令: --add / --list / --remove / --run-once / --daemon")

    elif args.cmd == "catalog":
        from finance.catalog import load_catalog
        cat = load_catalog()
        if args.script:
            print(json.dumps(cat.script_of(args.script), ensure_ascii=False, indent=2))
        elif args.match:
            r = cat.match(data_class=args.data_class, region=args.region, exchange=args.exchange,
                          trade_type=args.trade_type, time_level=args.time_level)
            if args.json:
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                for s in r:
                    print(f"  {s['id']:<16} {s['name']}  [{s['type']}]  ->  {s['script']}")
        else:
            for s in cat.list_sources():
                print(f"  {s['id']:<16} {s['name']}  [{s['type']}]  status={s['status']}")
            print(json.dumps(cat.summary(), ensure_ascii=False, indent=2))

    elif args.cmd == "taxonomy":
        from finance.taxonomy import load_taxonomy
        tax = load_taxonomy()
        if args.describe:
            print(json.dumps(tax.describe_instrument(args.describe), ensure_ascii=False, indent=2))
        elif args.exchanges:
            for ex in tax.exchanges_of_region(args.exchanges):
                print(f"  {ex['id']:<10} {ex['name']}")
        elif args.instruments:
            for inst in tax.instruments_of(data_class=args.data_class, region=args.region,
                                           exchange=args.exchange, trade_type=args.trade_type):
                print(f"  {inst['id']:<22} {inst['name']:<14} {inst['symbol']:<10} @{inst['exchange']}")
        else:
            print(json.dumps(tax.stats(), ensure_ascii=False, indent=2))

    elif args.cmd == "api":
        from finance.api import run
        run(port=args.port)

    elif args.cmd == "lance":
        from finance.lance.cli import main as lance_main
        sys.exit(lance_main(args.args or ["stats"]))

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
