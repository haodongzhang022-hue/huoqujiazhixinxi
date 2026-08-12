"""finance/lance/logs.py —— 运行日志 (run_logs 表)。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from finance.lance.store import get_store, json_dumps


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLogger:
    """写入 run_logs 表。"""

    def __init__(self, store=None):
        self.store = store or get_store()

    def log(self, run_type: str, status: str = "ok", message: str = "",
            channel_id: str = "", instrument_id: str = "", task_id: str = "",
            rows_count: int = 0, duration_ms: int = 0, detail: dict | None = None) -> str:
        log_id = str(uuid.uuid4())
        row = {
            "log_id": log_id,
            "run_type": run_type,
            "channel_id": channel_id,
            "instrument_id": instrument_id,
            "task_id": task_id,
            "status": status,
            "message": message,
            "rows_count": rows_count,
            "duration_ms": duration_ms,
            "detail": json_dumps(detail or {}),
            "created_at": _now(),
        }
        self.store.upsert("run_logs", [row], "log_id")
        return log_id

    def recent(self, run_type: str | None = None, limit: int = 20) -> list[dict]:
        where = f"run_type = '{run_type}'" if run_type else None
        return self.store.query("run_logs", where=where, limit=limit, order_by="created_at")

    def count(self) -> int:
        return self.store.count("run_logs")
