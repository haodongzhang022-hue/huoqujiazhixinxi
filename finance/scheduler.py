"""finance/scheduler.py —— 数据获取调度器 (频率/时间/自动获取)。

对齐 Issue #6: "可以设置自动获取的频率、时间等"

能力:
  - 每个 (数据源, 品种, 时间级别, 交易类型) 任务 = 一条调度规则
  - 调度类型: interval(每 N 秒/分/时/天) / cron(精确时间) / manual(手动)
  - 任务持久化: finance/data/scheduler.json (重启不丢)
  - 运行: python -m finance.scheduler --run-once  (单次扫描到期任务)
         python -m finance.scheduler --daemon     (常驻守护进程, 到点自动触发)
  - 记录: last_run / next_run / status / last_error

用法:
  python -m finance.scheduler --add --instrument CN.RB --source akshare --every 1d --at "16:00"
  python -m finance.scheduler --add --instrument CRYPTO.BTC --source ccxt --every 5m
  python -m finance.scheduler --list
  python -m finance.scheduler --run-once
  python -m finance.scheduler --remove 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from finance.registry import fetch_instrument
from finance.taxonomy import load_taxonomy

SCHEDULE_FILE = Path(__file__).resolve().parent / "data" / "scheduler.json"

# 人类可读频率 -> 秒
INTERVAL_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_interval(text: str) -> int | None:
    """'5m' / '1h' / '2d' -> 秒; 失败返回 None。"""
    text = text.strip().lower()
    num = ""
    unit = ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            unit += ch
    if not num or unit not in INTERVAL_UNITS:
        return None
    return int(num) * INTERVAL_UNITS[unit]


class Scheduler:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else SCHEDULE_FILE
        self.tasks: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.tasks = json.load(f)
            except Exception:
                self.tasks = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

    # ---------- 任务 CRUD ----------
    def add(self, instrument_id: str, source: str, time_level: str | None = None,
            trade_type: str | None = None, every: str | None = None,
            at: str | None = None, enabled: bool = True) -> dict:
        """新增调度任务。

        every: 频率 (5m / 1h / 1d / 2d ...)
        at:    每天固定时间 HH:MM (与 every 组合: 每天 at 时刻执行一次, 或 every 为基准 + at 偏移)
        """
        interval = parse_interval(every) if every else None
        task = {
            "id": str(uuid.uuid4())[:8],
            "instrument_id": instrument_id,
            "source": source,
            "time_level": time_level,
            "trade_type": trade_type,
            "every": every,
            "interval_seconds": interval,
            "at": at,
            "enabled": enabled,
            "status": "pending",
            "last_run": None,
            "next_run": self._calc_next(interval, at, last_run=None),
            "last_error": None,
            "created_at": _now(),
        }
        self.tasks.append(task)
        self.save()
        return task

    def remove(self, task_id: str) -> bool:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.get("id") != task_id]
        self.save()
        return len(self.tasks) < before

    def toggle(self, task_id: str, enabled: bool) -> bool:
        for t in self.tasks:
            if t.get("id") == task_id:
                t["enabled"] = enabled
                t["next_run"] = self._calc_next(t.get("interval_seconds"), t.get("at"), None)
                self.save()
                return True
        return False

    def list(self) -> list[dict]:
        return self.tasks

    # ---------- 调度计算 ----------
    @staticmethod
    def _calc_next(interval_seconds: int | None, at: str | None,
                   last_run: str | None) -> str | None:
        now = _utcnow()
        if interval_seconds and at:
            # 每天 at 时刻执行 (带频率语义: at 决定每天执行时刻)
            hh, mm = (int(x) for x in at.split(":"))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target.isoformat()
        if interval_seconds:
            base = datetime.fromisoformat(last_run) if last_run else now
            return (base + timedelta(seconds=interval_seconds)).isoformat()
        if at:
            hh, mm = (int(x) for x in at.split(":"))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target.isoformat()
        return None  # manual

    def due_tasks(self, now: datetime | None = None) -> list[dict]:
        now = now or _utcnow()
        due = []
        for t in self.tasks:
            if not t.get("enabled"):
                continue
            nr = t.get("next_run")
            if nr is None:
                continue  # manual 任务不自动触发
            try:
                next_dt = datetime.fromisoformat(nr)
            except Exception:
                continue
            if next_dt <= now:
                due.append(t)
        return due

    # ---------- 执行 ----------
    def run_task(self, task: dict) -> dict:
        tax = load_taxonomy()
        inst = tax.resolve_instrument(task["instrument_id"])
        if not inst:
            task["status"] = "error"
            task["last_error"] = f"品种未找到: {task['instrument_id']}"
            task["last_run"] = _now()
            self.save()
            return {"ok": False, "error": task["last_error"], "task": task}
        try:
            result = fetch_instrument(inst, source=task["source"],
                                      time_level=task.get("time_level"),
                                      trade_type=task.get("trade_type"))
            task["status"] = "ok"
            task["last_error"] = None
            task["last_run"] = _now()
            task["next_run"] = self._calc_next(task.get("interval_seconds"), task.get("at"),
                                               task.get("last_run"))
            self.save()
            return {"ok": True, "task": task, "result": result}
        except Exception as e:
            task["status"] = "error"
            task["last_error"] = str(e)
            task["last_run"] = _now()
            task["next_run"] = self._calc_next(task.get("interval_seconds"), task.get("at"),
                                               task.get("last_run"))
            self.save()
            return {"ok": False, "error": str(e), "task": task}

    def run_due(self) -> list[dict]:
        due = self.due_tasks()
        results = []
        for t in due:
            results.append(self.run_task(t))
        return results

    def daemon(self, interval: float = 30.0, once: bool = False):
        """常驻守护: 每 interval 秒扫描一次到期任务并触发。"""
        print(f"[scheduler] 守护进程启动, 每 {interval}s 扫描 (Ctrl+C 退出)")
        while True:
            results = self.run_due()
            for r in results:
                t = r.get("task", {})
                print(f"  [{t.get('id')}] {t.get('instrument_id')} <- {t.get('source')}: "
                      f"{'OK' if r.get('ok') else 'ERROR ' + str(r.get('error', ''))}")
            if once:
                break
            time.sleep(interval)


def main():
    ap = argparse.ArgumentParser(description="金融数据获取调度器")
    ap.add_argument("--add", action="store_true", help="新增任务")
    ap.add_argument("--instrument", help="品种 id")
    ap.add_argument("--source", help="数据源 id")
    ap.add_argument("--time-level", help="时间级别")
    ap.add_argument("--trade-type", help="交易类型")
    ap.add_argument("--every", help="频率 (5m/1h/1d/2d...)")
    ap.add_argument("--at", help="每天时刻 HH:MM")
    ap.add_argument("--list", action="store_true", help="列出任务")
    ap.add_argument("--remove", metavar="TASK_ID", help="删除任务")
    ap.add_argument("--toggle", metavar="TASK_ID", help="启用/停用任务 (配合 --enabled)")
    ap.add_argument("--enabled", action="store_true", help="启用")
    ap.add_argument("--disabled", action="store_true", help="停用")
    ap.add_argument("--run-once", action="store_true", help="扫描执行一次到期任务")
    ap.add_argument("--daemon", action="store_true", help="常驻守护进程")
    ap.add_argument("--scan-interval", type=float, default=30.0, help="守护扫描间隔秒")
    args = ap.parse_args()

    sched = Scheduler()

    if args.add:
        if not args.instrument or not args.source:
            print("--add 需要 --instrument 和 --source", file=sys.stderr)
            sys.exit(1)
        t = sched.add(args.instrument, args.source, time_level=args.time_level,
                      trade_type=args.trade_type, every=args.every, at=args.at)
        print(json.dumps(t, ensure_ascii=False, indent=2))
        return
    if args.remove:
        ok = sched.remove(args.remove)
        print("已删除" if ok else f"未找到任务 {args.remove}")
        return
    if args.toggle:
        enabled = args.enabled and not args.disabled
        ok = sched.toggle(args.toggle, enabled)
        print("已更新" if ok else f"未找到任务 {args.toggle}")
        return
    if args.list:
        if not sched.tasks:
            print("(空)")
        for t in sched.tasks:
            print(f"  [{t['id']}] {t['instrument_id']} <- {t['source']} "
                  f"every={t.get('every') or '-'} at={t.get('at') or '-'} "
                  f"next={t.get('next_run') or 'manual'} status={t.get('status')} enabled={t.get('enabled')}")
        return
    if args.run_once:
        results = sched.run_due()
        for r in results:
            t = r.get("task", {})
            print(f"  [{t.get('id')}] {t.get('instrument_id')} <- {t.get('source')}: "
                  f"{'OK' if r.get('ok') else 'ERROR ' + str(r.get('error', ''))}")
        print(f"本次触发 {len(results)} 个任务")
        return
    if args.daemon:
        sched.daemon(interval=args.scan_interval)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
