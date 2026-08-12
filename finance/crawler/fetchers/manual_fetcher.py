"""finance/crawler/fetchers/manual_fetcher.py —— 人工录入渠道 (manual)。

用于无法自动获取的数据: 人工在 params.manual_rows 中录入原始行, 或由外部写入
channels.params.manual_data (JSON 文件路径), 引擎直接入库。
"""

from __future__ import annotations

import json
from pathlib import Path


def fetch(store, payload: dict) -> dict:
    ch = payload["channel"]
    params = payload["params"]
    rows = []
    # 1) 直接内联的 manual_rows
    if params.get("manual_rows"):
        rows = params["manual_rows"]
    # 2) 文件路径
    elif params.get("manual_file"):
        p = Path(params["manual_file"])
        if p.exists():
            try:
                rows = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(rows, dict):
                    rows = rows.get("rows", [])
            except Exception as e:
                return {"ok": False, "error": f"manual_file 解析失败: {e}", "raw_rows": []}
    if not rows:
        return {"ok": False, "error": "manual 渠道无数据 (配置 params.manual_rows 或 manual_file)",
                "raw_rows": []}
    return {"ok": True, "raw_rows": rows, "demo": False, "detail": {"rows": len(rows)}}
