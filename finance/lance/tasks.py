"""finance/lance/tasks.py —— 自动获取数据定时爬虫 (fetch_tasks 表 + 任务编排)。

对齐 Issue #6: "一个自动获取数据的定时爬虫"
  - 每个任务 = fetch_tasks 表一行: 渠道 + 品种 + 时间级别 + 交易类型 + 频率/时刻
  - 调度类型: interval (每 N 秒/分/时/天) / cron (cron 表达式) / daily-at (每日 HH:MM) / once
  - run_due(): 扫描到期任务并执行 (供守护进程/CI 周期调用)
  - daemon(): 常驻守护 (也可由 .cnb.yml 定时任务/外部 cron 周期调用 run_due)
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from finance.lance.store import get_store, json_dumps

INTERVAL_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_interval(text: str) -> int | None:
    """'5m'/'1h'/'2d' -> 秒。"""
    text = (text or "").strip().lower()
    num, unit = "", ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            unit += ch
    try:
        return int(float(num) * INTERVAL_UNITS.get(unit, 60))
    except (ValueError, TypeError):
        return None


def _fmt(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class TaskManager:
    def __init__(self, store=None):
        self.store = store or get_store()

    def _store(self):
        return self.store

    # ---------- 增删查 ----------
    def add(self, channel_id: str, instrument_id: str = "", time_level: str = "",
            trade_type: str = "", every: str = "", at: str = "", cron: str = "",
            name: str = "", enabled: bool = True, params: dict | None = None) -> str:
        """新增自动获取任务。every 与 at/cron 二选一。"""
        if not every and not at and not cron:
            raise ValueError("必须提供 every(间隔) 或 at(每日时刻) 或 cron(表达式) 之一")
        task_id = str(uuid.uuid4())
        now = _now()
        task_type = "interval" if every else ("daily-at" if at else "cron")
        row = {
            "task_id": task_id,
            "name": name or f"{channel_id}:{instrument_id or '*'}",
            "channel_id": channel_id,
            "instrument_id": instrument_id,
            "time_level": time_level,
            "trade_type": trade_type,
            "task_type": task_type,
            "every": every,
            "cron": cron,
            "at": at,
            "enabled": enabled,
            "params": json_dumps(params or {}),
            "next_run_at": _compute_next(every, at, cron, now),
            "last_run_at": "",
            "last_status": "",
            "last_error": "",
            "run_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.store.upsert("fetch_tasks", [row], "task_id")
        return task_id

    def list(self, enabled: bool | None = None) -> list[dict]:
        where = "enabled = true" if enabled else None
        return self.store.query("fetch_tasks", where=where, order_by="created_at")

    def get(self, task_id: str) -> dict | None:
        return self.store.get("fetch_tasks", "task_id", task_id)

    def remove(self, task_id: str):
        self.store.delete("fetch_tasks", f"task_id = '{task_id}'")

    def enable(self, task_id: str, enabled: bool = True):
        self.store.upsert("fetch_tasks", [{"task_id": task_id, "enabled": enabled,
                                           "updated_at": _now()}], "task_id")

    # ---------- 执行 ----------
    def run_due(self, now: str | None = None) -> list[dict]:
        """扫描到期任务并执行 (供守护进程/外部 cron 周期调用)。"""
        now = now or _now()
        results = []
        for task in self.list(enabled=True):
            next_run = task.get("next_run_at") or ""
            if next_run and next_run <= now:
                results.append(self._execute(task, now))
        return results

    def run_task(self, task_id: str) -> dict:
        task = self.get(task_id)
        if not task:
            return {"ok": False, "error": f"任务不存在: {task_id}"}
        return self._execute(task, _now())

    def run_all(self) -> list[dict]:
        """立即执行所有启用任务 (忽略调度时间)。"""
        return [self._execute(t, _now()) for t in self.list(enabled=True)]

    def _execute(self, task: dict, now: str) -> dict:
        t0 = time.time()
        channel_id = task["channel_id"]
        try:
            from finance.crawler.dispatcher import fetch_channel
            res = fetch_channel(
                channel_id,
                instrument_id=task.get("instrument_id") or None,
                time_level=task.get("time_level") or None,
                trade_type=task.get("trade_type") or None,
                store=self.store,
            )
            status = "ok" if res.get("ok") else ("partial" if res.get("status") == "partial" else "failed")
            error = "; ".join(res.get("errors") or [])
            update = {
                "task_id": task["task_id"],
                "last_run_at": now,
                "last_status": status,
                "last_error": error[:500],
                "run_count": (task.get("run_count") or 0) + 1,
                "next_run_at": _compute_next(task.get("every"), task.get("at"),
                                             task.get("cron"), now),
                "updated_at": now,
            }
            self.store.upsert("fetch_tasks", [update], "task_id")
            return {"ok": status != "failed", "task_id": task["task_id"],
                    "channel_id": channel_id, "instrument_id": task.get("instrument_id"),
                    "status": status, "error": error,
                    "duration_ms": int((time.time() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            update = {
                "task_id": task["task_id"],
                "last_run_at": now,
                "last_status": "failed",
                "last_error": str(e)[:500],
                "run_count": (task.get("run_count") or 0) + 1,
                "next_run_at": _compute_next(task.get("every"), task.get("at"),
                                             task.get("cron"), now),
                "updated_at": now,
            }
            self.store.upsert("fetch_tasks", [update], "task_id")
            return {"ok": False, "task_id": task["task_id"], "channel_id": channel_id,
                    "status": "failed", "error": str(e),
                    "duration_ms": int((time.time() - t0) * 1000)}

    # ---------- 守护 ----------
    def daemon(self, interval_sec: int = 60, once: bool = False):
        """常驻守护: 每 interval_sec 秒扫描一次到期任务。"""
        print(f"[tasks.daemon] 启动, 扫描间隔 {interval_sec}s (Ctrl+C 退出)")
        while True:
            try:
                results = self.run_due()
                for r in results:
                    print(f"  [run] {r.get('channel_id')} {r.get('instrument_id')} "
                          f"-> {r.get('status')} {r.get('duration_ms')}ms")
            except KeyboardInterrupt:
                print("[tasks.daemon] 退出")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[tasks.daemon] 错误: {e}")
            if once:
                break
            time.sleep(interval_sec)


def _compute_next(every: str, at: str, cron: str, now: str) -> str:
    """计算下次运行时间 (简化实现; 完整 cron 解析可扩展)。"""
    base = datetime.fromisoformat(now)
    if every:
        sec = parse_interval(every) or 3600
        return _fmt(base + timedelta(seconds=sec))
    if at:
        try:
            hh, mm = (at.split(":") + ["00"])[:2]
            nxt = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if nxt <= base:
                nxt += timedelta(days=1)
            return _fmt(nxt)
        except (ValueError, TypeError):
            return _fmt(base + timedelta(hours=24))
    if cron:
        # 简化: 每分钟都视为可执行 (调用方 run_due 按时间判断), 默认 +1h 兜底
        # 完整 cron 解析: 建议接入 croniter
        try:
            import croniter  # noqa: F401
            return _fmt(croniter.croniter(cron, base).get_next(datetime))
        except ImportError:
            return _fmt(base + timedelta(hours=1))
    return _fmt(base + timedelta(hours=24))
