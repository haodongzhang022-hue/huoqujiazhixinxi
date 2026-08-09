"""finance/lance/store.py —— LanceDB 存储核心 (连接 / 建表 / 通用 CRUD)。

统一封装:
  - 连接 & 建表 (七张表, 缺失自动创建, 列缺失自动补列)
  - 通用 upsert (按主键 merge_insert)
  - 通用查询 / 删除 / 清空
  - schema 升级: 新列自动 ALTER 追加
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lancedb

from finance.lance.schema import TABLES, LANCE_DIR

_LOCK = threading.Lock()
_store_cache: dict[str, "LanceStore"] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(obj: Any) -> str:
    """JSON 序列化 (处理 numpy/date 等)。"""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj

    def _default(o):
        try:
            import numpy as np
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            if isinstance(o, np.bool_):
                return bool(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
        except ImportError:
            pass
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)

    return json.dumps(obj, ensure_ascii=False, default=_default)


class LanceStore:
    """LanceDB 统一存储。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else LANCE_DIR
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_path))
        self._ensure_tables()

    # ---------- 建表/升级 ----------
    def _ensure_tables(self):
        existing = set(self.db.table_names())
        for name, cols in TABLES.items():
            if name not in existing:
                # 用一行样例建表 (LanceDB 以首行定型), 随后删除占位行
                row = {c: _sample_value(c, name) for c in cols}
                t = self.db.create_table(name, data=[row])
                try:
                    t.delete("1=1")
                except Exception:
                    pass
            else:
                self._upgrade_table(name, cols)

    def _upgrade_table(self, name: str, cols: list[str]):
        """补列: 表已存在但缺标准列时追加 (LanceDB add_columns)。"""
        try:
            t = self.db.open_table(name)
            schema = t.schema
            have = set(schema.names)
            missing = [c for c in cols if c not in have]
            for c in missing:
                try:
                    t.add_columns([{"name": c, "data_type": _sample_value(c, name)}])
                except Exception:
                    pass  # 并行建表等竞态, 忽略
        except Exception:
            pass

    # ---------- 通用 CRUD ----------
    def table(self, name: str):
        return self.db.open_table(name)

    def upsert(self, table: str, rows: list[dict], key: str):
        """按主键 upsert (merge_insert)。支持部分字段更新 (先读后合并, 不丢已有列)。"""
        if not rows:
            return 0
        t = self.table(table)
        # 标准列全集 (不含 ts, ts 自动生成)
        std = [c for c in TABLES[table] if c not in ("ts",)]
        # 1) 先读已有行 (部分字段更新时合并, 避免其它列被清空)
        existing: dict[str, dict] = {}
        keys = [str(r.get(key)) for r in rows if r.get(key) is not None]
        if keys:
            try:
                for k in keys:
                    try:
                        hit = self.query(table, where=f"{key} = '{k}'", limit=1)
                        if hit:
                            existing[k] = hit[0]
                    except Exception:
                        pass
            except Exception:
                pass
        now = _now()
        cleaned = []
        # JSON 字符串列 (读回时被反序列化, 写回前需重新序列化)
        json_cols = {"raw", "extra", "source_meta", "params", "detail",
                     "probe_result", "auth", "storage", "schedule",
                     "disclosure", "requires", "fetchers", "cleaning",
                     "ext", "data_classes", "regions", "exchanges"}
        for r in rows:
            k = str(r.get(key) or "")
            merged = dict(existing.get(k) or {})
            for c in std:
                if c in r:
                    merged[c] = r[c]
            # 统一序列化 JSON 列 (existing 继承或新值, 只要是非 str 就转 JSON 字符串)
            for c in std:
                v = merged.get(c)
                if c in json_cols and isinstance(v, (dict, list)):
                    merged[c] = json_dumps(v)
            item = {c: merged.get(c) for c in std}
            item["ts"] = now
            cleaned.append(item)
        t.merge_insert(key) \
            .when_matched_update_all() \
            .when_not_matched_insert_all() \
            .execute(cleaned)
        return len(cleaned)

    def delete(self, table: str, where: str):
        self.table(table).delete(where)

    def truncate(self, table: str):
        try:
            self.table(table).delete("1=1")
        except Exception:
            pass

    def count(self, table: str) -> int:
        try:
            return self.table(table).count_rows()
        except Exception:
            return 0

    def query(self, table: str, where: str | None = None, limit: int | None = None,
              order_by: str | None = None) -> list[dict]:
        """查询 -> list[dict] (已做 JSON 字段反序列化)。"""
        t = self.table(table)
        try:
            if where:
                tbl = t.search().where(where, prefilter=True)
                if limit:
                    tbl = tbl.limit(limit)
                df = tbl.to_pandas()
            else:
                df = t.to_pandas()
                if order_by and order_by in df.columns:
                    df = df.sort_values(order_by, ascending=False)
                if limit:
                    df = df.head(limit)
        except Exception:
            df = t.to_pandas()
            if order_by and order_by in df.columns:
                df = df.sort_values(order_by, ascending=False)
            if limit:
                df = df.head(limit)
        return _rows_to_dicts(df)

    def all(self, table: str, limit: int | None = None) -> list[dict]:
        return self.query(table, limit=limit)

    def get(self, table: str, key: str, value: Any) -> dict | None:
        rows = self.query(table, where=f"{key} = '{value}'", limit=1)
        return rows[0] if rows else None

    def list_tables(self) -> list[str]:
        return sorted(self.db.table_names())

    def stats(self) -> dict:
        return {name: self.count(name) for name in self.list_tables()}


def get_store(db_path: str | Path | None = None) -> LanceStore:
    """全局单例 store。"""
    key = str(db_path) if db_path else "default"
    with _LOCK:
        if key not in _store_cache:
            _store_cache[key] = LanceStore(db_path)
        return _store_cache[key]


def _sample_value(col: str, table: str = "") -> Any:
    """按列名(及表名)给出样例值 (建表用, 与标准列类型对齐)。"""
    # params.value 统一存 JSON 字符串; data_records.value 存数值
    if table == "params" and col == "value":
        return ""
    if col in ("enabled", "required", "active"):
        return False
    if col in ("score",):
        return 0.0
    if col in ("rows_count", "duration_ms", "run_count"):
        return 0
    if col in ("open", "high", "low", "close", "volume", "amount", "value"):
        return 0.0
    if col in ("ts", "created_at", "updated_at", "last_run_at", "next_run_at"):
        return _now()
    if col in ("raw", "extra", "source_meta", "params", "detail", "probe_result",
               "auth", "storage", "schedule", "disclosure", "requires", "fetchers",
               "cleaning", "ext", "data_classes", "regions", "exchanges"):
        return "{}"  # JSON 字符串列
    return ""


def _rows_to_dicts(df) -> list[dict]:
    """DataFrame -> list[dict], 把 JSON 字符串列反序列化为对象, numpy 标量转原生。"""
    import numpy as np

    out = []
    for _, row in df.iterrows():
        item = {}
        for col in df.columns:
            v = row[col]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                item[col] = None
                continue
            if isinstance(v, np.generic):
                v = v.item()
            if isinstance(v, str):
                # JSON 字符串列尝试反序列化
                if col in ("raw", "extra", "source_meta", "params", "detail",
                           "probe_result", "auth", "storage", "schedule",
                           "disclosure", "requires", "fetchers", "cleaning",
                           "ext", "data_classes", "regions", "exchanges"):
                    try:
                        item[col] = json.loads(v)
                    except Exception:
                        item[col] = v
                else:
                    item[col] = v
            elif hasattr(v, "tolist"):
                item[col] = v.tolist() if not isinstance(v, (list, tuple)) else list(v)
            else:
                item[col] = v
        out.append(item)
    return out
