"""finance/fetchers/manual_fetcher.py —— 人工/半自动采集适配器。

用于: 官方 PDF/Excel/网站手工下载的数据, 临时录入, 或接入自定义脚本的数据。

payload 支持传入 data (直接写入缓存) 或按 note 记录人工标记。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def fetch(payload: dict) -> dict:
    data = payload.get("data")
    note = payload.get("note", "人工录入")
    if data is None:
        # 无数据则只记录人工占位
        data = {"kind": "manual", "note": note, "rows": []}
    return {"ok": True, "source": "manual", "demo": False,
            "instrument_id": payload.get("instrument_id", ""),
            "note": note,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": data}


def main():
    ap = argparse.ArgumentParser(description="人工采集适配器")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--note", default="人工录入")
    ap.add_argument("--data-json", help="JSON 数据文件路径")
    args = ap.parse_args()
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    data = None
    if args.data_json:
        with open(args.data_json, encoding="utf-8") as f:
            data = json.load(f)
    payload = {**inst, "instrument": inst, "instrument_id": inst["id"],
               "note": args.note, "data": data}
    print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
