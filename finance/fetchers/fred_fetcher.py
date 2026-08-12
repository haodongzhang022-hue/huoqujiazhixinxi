"""finance/fetchers/fred_fetcher.py —— FRED 数据源适配器 (美联储经济数据库, 宏观/利率/债券)。

覆盖: 美国及全球宏观序列 (CPI/失业率/利率/GDP/收益率曲线...), 发布日历。

依赖: 环境变量 FRED_API_KEY (免费注册 https://fred.stlouisfed.org/docs/api/api_key.html)
      urllib 标准库直连, 无需第三方库。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

FRED_BASE = "https://api.stlouisfed.org/fred"
FRED_KEY = os.environ.get("FRED_API_KEY", "")


def _get(path: str, params: dict) -> dict:
    if not FRED_KEY:
        raise RuntimeError("缺少 FRED_API_KEY 环境变量 (https://fred.stlouisfed.org/docs/api/api_key.html)")
    params = {**params, "api_key": FRED_KEY, "file_type": "json"}
    url = f"{FRED_BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(payload: dict) -> dict:
    inst = payload.get("instrument") or {}
    series_id = payload.get("symbol", "") or inst.get("symbol", "CPIAUCSL")
    tl = payload.get("time_level", "1M")
    freq_map = {"1d": "d", "1w": "w", "1M": "m", "1Q": "q", "1Y": "a"}
    freq = freq_map.get(tl, "m")

    obs = _get("series/observations", {"series_id": series_id, "frequency": freq,
                                       "sort_order": "desc", "limit": 500})
    rows = [{"time": o.get("date"), "value": o.get("value")} for o in obs.get("observations", [])
            if o.get("value") not in (None, ".")]
    meta = _get("series", {"series_id": series_id}).get("seriess", [{}])[0]
    return {"ok": True, "source": "fred", "demo": False,
            "instrument_id": payload.get("instrument_id", ""),
            "series_id": series_id, "frequency": freq,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": {"kind": "series", "meta": meta, "rows": rows}}


def main():
    ap = argparse.ArgumentParser(description="FRED 宏观适配器")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--time-level", default="1M")
    args = ap.parse_args()
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument(args.instrument)
    if not inst:
        print(f"未找到品种: {args.instrument}", file=sys.stderr)
        sys.exit(1)
    payload = {**inst, "instrument": inst, "instrument_id": inst["id"], "time_level": args.time_level}
    try:
        print(json.dumps(fetch(payload), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[fred] 获取失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
