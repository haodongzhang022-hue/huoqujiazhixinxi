"""finance/lance/datastore.py —— 数据落库与查询 (data_records 表)。

统一管理获取到的数据: 标准字段宽表 + raw 原始行 + 查询/统计。
"""

from __future__ import annotations

from finance.lance.store import get_store


class DataStore:
    def __init__(self, store=None):
        self.store = store or get_store()

    def count(self) -> int:
        return self.store.count("data_records")

    def query(self, channel_id: str | None = None, instrument_id: str | None = None,
              data_class: str | None = None, region: str | None = None,
              exchange: str | None = None, time_level: str | None = None,
              limit: int = 100, where: str | None = None) -> list[dict]:
        conds = []
        if channel_id:
            conds.append(f"channel_id = '{channel_id}'")
        if instrument_id:
            conds.append(f"instrument_id = '{instrument_id}'")
        if data_class:
            conds.append(f"data_class = '{data_class}'")
        if region:
            conds.append(f"region = '{region}'")
        if exchange:
            conds.append(f"exchange = '{exchange}'")
        if time_level:
            conds.append(f"time_level = '{time_level}'")
        if where:
            conds.append(where)
        w = " AND ".join(conds) if conds else None
        return self.store.query("data_records", where=w, limit=limit, order_by="ts")

    def stats(self) -> dict:
        rows = self.store.query("data_records", limit=200000)
        by_channel, by_class, by_instrument = {}, {}, {}
        for r in rows:
            c = r.get("channel_id") or "?"
            by_channel[c] = by_channel.get(c, 0) + 1
            dc = r.get("data_class") or "?"
            by_class[dc] = by_class.get(dc, 0) + 1
            iid = r.get("instrument_id") or "?"
            by_instrument[iid] = by_instrument.get(iid, 0) + 1
        return {
            "total": len(rows),
            "by_channel": dict(sorted(by_channel.items(), key=lambda x: -x[1])),
            "by_data_class": dict(sorted(by_class.items(), key=lambda x: -x[1])),
            "by_instrument": dict(sorted(by_instrument.items(), key=lambda x: -x[1])),
        }

    def latest(self, channel_id: str, instrument_id: str, limit: int = 10) -> list[dict]:
        return self.query(channel_id=channel_id, instrument_id=instrument_id, limit=limit)

    def recent(self, limit: int = 20) -> list[dict]:
        return self.store.query("data_records", limit=limit, order_by="created_at")
