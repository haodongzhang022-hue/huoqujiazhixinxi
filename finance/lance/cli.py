"""finance/lance/cli.py —— LanceDB 统一管理 CLI (python -m finance.lance.cli)。

子命令:
  init        建表 + 种子初始化 (现有数据源 -> channels/column_defs/params)
  channels    渠道列表/查看
  columns     列定义列表
  params      参数列表
  fetch       触发渠道获取 (自动获取数据爬虫的单次执行)
  tasks       自动获取任务: add/list/run-due/run-all/remove
  discovery   渠道挖掘: discover/evaluate/promote/run
  data        数据查询/统计
  logs        运行日志
  stats       各表行数统计
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="LanceDB 统一数据管理 (渠道/列/参数/任务/数据/日志/挖掘)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # init
    p = sub.add_parser("init", help="建表 + 种子初始化")
    p.add_argument("--seed", action="store_true", default=True, help="从 catalog 迁移种子渠道")

    # channels
    p = sub.add_parser("channels", help="渠道列表")
    p.add_argument("--status")
    p.add_argument("--json", action="store_true")

    # columns
    p = sub.add_parser("columns", help="列定义列表")
    p.add_argument("--channel")
    p.add_argument("--json", action="store_true")

    # params
    p = sub.add_parser("params", help="参数列表")
    p.add_argument("--channel", required=True)
    p.add_argument("--scope")
    p.add_argument("--json", action="store_true")

    # fetch
    p = sub.add_parser("fetch", help="触发渠道获取")
    p.add_argument("--channel", required=True)
    p.add_argument("--instrument")
    p.add_argument("--time-level")
    p.add_argument("--trade-type")

    # tasks
    p = sub.add_parser("tasks", help="自动获取任务")
    p.add_argument("--add", action="store_true")
    p.add_argument("--channel", help="渠道")
    p.add_argument("--instrument", help="品种")
    p.add_argument("--time-level")
    p.add_argument("--trade-type")
    p.add_argument("--every", help="间隔 如 5m/1h/1d")
    p.add_argument("--at", help="每日时刻 HH:MM")
    p.add_argument("--list", action="store_true")
    p.add_argument("--run-due", action="store_true")
    p.add_argument("--run-all", action="store_true")
    p.add_argument("--remove", help="任务 id")

    # discovery
    p = sub.add_parser("discovery", help="渠道挖掘")
    p.add_argument("--discover", action="store_true")
    p.add_argument("--evaluate", action="store_true")
    p.add_argument("--promote", help="候选 id -> 转正")
    p.add_argument("--channel-id", help="转正后渠道 id")
    p.add_argument("--run", action="store_true", help="发现+评估+自动转正")
    p.add_argument("--auto-promote", action="store_true")
    p.add_argument("--list", action="store_true")

    # data
    p = sub.add_parser("data", help="数据查询/统计")
    p.add_argument("--channel")
    p.add_argument("--instrument")
    p.add_argument("--data-class")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--stats", action="store_true")

    # logs
    p = sub.add_parser("logs", help="运行日志")
    p.add_argument("--run-type")
    p.add_argument("--limit", type=int, default=20)

    # stats
    p = sub.add_parser("stats", help="各表行数统计")

    args = ap.parse_args(argv)
    from finance.lance.store import get_store

    store = get_store()

    if args.cmd == "init":
        from finance.lance.registry import ChannelRegistry
        reg = ChannelRegistry(store)
        res = reg.seed_from_catalog()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "channels":
        from finance.lance.registry import ChannelRegistry
        rows = ChannelRegistry(store).list_channels(status=args.status)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            for r in rows:
                print(f"  {r.get('channel_id'):<18} {r.get('name',''):<40} "
                      f"kind={r.get('kind',''):<10} status={r.get('status',''):<8} "
                      f"enabled={r.get('enabled','')}")
    elif args.cmd == "columns":
        from finance.lance.registry import ChannelRegistry
        rows = ChannelRegistry(store).list_column_defs(channel_id=args.channel)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            for r in rows:
                print(f"  {r.get('channel_id'):<14} {r.get('source_col',''):<18} -> "
                      f"{r.get('standard_col',''):<10} {r.get('col_type',''):<8} {r.get('description','')}")
    elif args.cmd == "params":
        from finance.lance.registry import ChannelRegistry
        rows = ChannelRegistry(store).get_params(args.channel, scope=args.scope)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            for r in rows:
                print(f"  [{r.get('scope',''):<10}] {r.get('key',''):<28} = {r.get('value')}  {r.get('description','')}")
    elif args.cmd == "fetch":
        from finance.crawler.dispatcher import fetch_channel
        res = fetch_channel(args.channel, instrument_id=args.instrument,
                            time_level=args.time_level, trade_type=args.trade_type)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "tasks":
        from finance.lance.tasks import TaskManager
        tm = TaskManager(store)
        if args.add:
            if not args.channel:
                print("--add 需要 --channel", file=sys.stderr)
                sys.exit(1)
            tid = tm.add(args.channel, instrument_id=args.instrument or "",
                         time_level=args.time_level or "", trade_type=args.trade_type or "",
                         every=args.every or "", at=args.at or "")
            print(f"任务已创建: {tid}")
        elif args.run_due:
            res = tm.run_due()
            for r in res:
                print(f"  {r.get('channel_id')} {r.get('instrument_id') or ''} -> {r.get('status')}")
        elif args.run_all:
            res = tm.run_all()
            for r in res:
                print(f"  {r.get('channel_id')} {r.get('instrument_id') or ''} -> {r.get('status')}")
        elif args.remove:
            tm.remove(args.remove)
            print(f"已删除任务: {args.remove}")
        else:
            for t in tm.list():
                sched = t.get('every') or t.get('at') or t.get('cron') or '-'
                print(f"  {t.get('task_id')[:8]}  {t.get('channel_id'):<14} "
                      f"{t.get('instrument_id') or '*':<14} every={sched:<8} "
                      f"enabled={t.get('enabled')} next={t.get('next_run_at')}")
    elif args.cmd == "discovery":
        from finance.lance.discovery import ChannelDiscovery
        d = ChannelDiscovery(store)
        if args.discover:
            found = d.discover()
            print(f"发现 {len(found)} 个候选:")
            for c in found[:20]:
                print(f"  {c.get('candidate_id')}  {c.get('name','')[:40]:<42} {c.get('url','')}")
        elif args.evaluate:
            res = d.evaluate()
            for r in res:
                print(f"  {r['candidate_id']}  score={r['score']:>3}  {r['status']:<8} {r['name'][:36]:<38} {r['url']}")
        elif args.promote:
            res = d.promote(args.promote, channel_id=args.channel_id)
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        elif args.run:
            res = d.run_pipeline(auto_promote=args.auto_promote)
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        else:
            for c in d.list_candidates(limit=50):
                print(f"  {c.get('candidate_id')}  {c.get('status',''):<10} score={c.get('score'):>3}  "
                      f"{c.get('name','')[:36]:<38} {c.get('url','')}")
    elif args.cmd == "data":
        from finance.lance.datastore import DataStore
        ds = DataStore(store)
        if args.stats:
            print(json.dumps(ds.stats(), ensure_ascii=False, indent=2))
        else:
            rows = ds.query(channel_id=args.channel, instrument_id=args.instrument,
                            data_class=args.data_class, limit=args.limit)
            for r in rows:
                print(f"  {r.get('ts','')}  [{r.get('channel_id','')}] {r.get('instrument_id',''):<14} "
                      f"close={r.get('close')} value={r.get('value')} title={(r.get('title') or '')[:30]}")
            print(f"  ... 共 {len(rows)} 行")
    elif args.cmd == "logs":
        from finance.lance.logs import RunLogger
        rows = RunLogger(store).recent(run_type=args.run_type, limit=args.limit)
        for r in rows:
            print(f"  {r.get('created_at','')}  [{r.get('run_type',''):<9}] {r.get('status',''):<7} "
                  f"{r.get('channel_id',''):<14} rows={r.get('rows_count')} {r.get('message','')[:60]}")
    elif args.cmd == "stats":
        print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
