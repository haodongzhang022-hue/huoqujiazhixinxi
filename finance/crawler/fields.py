"""finance/crawler/fields.py —— 标准字段映射与清洗 (读 column_defs / params 表)。

通用模板的一部分: 把渠道原始行 (列名 -> 值) 映射为框架标准字段。
映射规则来自 LanceDB column_defs 表 (本渠道列定义文件), 每个渠道独立配置:
  source_col  ->  standard_col (ts/open/high/low/close/volume/title/link/content/value...)
  col_type / cleaning (清洗规则)
"""

from __future__ import annotations

import json
import re
from datetime import datetime


def clean_value(value, col_type: str = "string", cleaning: dict | None = None):
    """按列类型与清洗规则处理单个值。"""
    cleaning = cleaning or {}
    if value is None:
        return None
    if isinstance(value, str):
        if cleaning.get("trim", True):
            value = value.strip()
        if cleaning.get("remove_commas"):
            value = value.replace(",", "").replace("，", "")
        if cleaning.get("remove_chars"):
            for ch in cleaning["remove_chars"]:
                value = value.replace(ch, "")
    # 空值
    if value == "" or (isinstance(value, str) and value in ("-", "--", "—", "N/A", "null", "None")):
        return None
    try:
        if col_type == "float":
            return float(str(value).replace("%", "").replace(",", ""))
        if col_type == "int":
            return int(float(str(value).replace(",", "").replace("%", "")))
        if col_type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "是", "y")
        if col_type == "datetime":
            return parse_datetime(str(value), cleaning.get("parse_date"))
        if col_type == "json":
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return value
            return value
    except (ValueError, TypeError):
        return None
    return value


def parse_datetime(text: str, fmt: str | None = None):
    """宽松日期解析 -> 'YYYY-MM-DDTHH:MM:SS' 或 'YYYY-MM-DD'。"""
    text = text.strip()
    if not text:
        return None
    if fmt:
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    # ISO
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        pass
    # 常见格式
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
              "%Y/%m/%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, f).isoformat(timespec="seconds")
        except ValueError:
            continue
    return text


def map_row(raw_row: dict, col_defs: list[dict], default_ts_col: str | None = None) -> dict:
    """按 column_defs 把原始行映射为标准行。

    - col_defs: [{source_col, standard_col, col_type, cleaning}]
    - 返回 {standard_col: value, raw: {原始行}}
    """
    mapped: dict = {}
    by_source = {d["source_col"]: d for d in col_defs if d.get("enabled", True)}
    # 大小写不敏感兜底
    lower_map = {str(k).lower(): v for k, v in by_source.items()}
    for src, val in raw_row.items():
        if src.startswith("_"):
            continue
        d = by_source.get(src) or lower_map.get(str(src).lower())
        if not d:
            continue
        std = d.get("standard_col")
        if not std:
            continue
        mapped[std] = clean_value(val, d.get("col_type", "string"), d.get("cleaning") or {})
    # 时间列: 若标准行有 ts 则规范化; 否则尝试从任何列提取
    if "ts" not in mapped and default_ts_col:
        if default_ts_col in raw_row:
            mapped["ts"] = parse_datetime(str(raw_row[default_ts_col]))
    return {"mapped": mapped, "raw": raw_row}


def map_rows(raw_rows: list[dict], col_defs: list[dict], default_ts_col: str | None = None) -> list[dict]:
    out = []
    for r in raw_rows:
        if r.get("_error"):
            continue
        m = map_row(r, col_defs, default_ts_col)
        if m["mapped"]:
            out.append(m)
    return out
