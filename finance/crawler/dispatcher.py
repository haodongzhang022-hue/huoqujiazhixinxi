"""finance/crawler/dispatcher.py —— 渠道调度分发器 (通用模板的编排层)。

职责 (与渠道无关):
  1. 从 LanceDB 读取渠道定义 (channels 表): 地址/方法/脚本/存储
  2. 从 LanceDB 读取列定义 (column_defs 表): 渠道列 -> 标准字段
  3. 从 LanceDB 读取参数 (params 表): 渠道/品种/获取器/请求级参数
  4. 加载分渠道 fetcher 模块 (或通用引擎) 执行获取 -> 原始行
  5. fields.map_rows 映射为标准行
  6. 落库 data_records 表 (按 record_id 去重) + 记录 run_logs

新渠道只需: channels + column_defs + params 三条记录入库 (或走 discovery 转正),
无需改动本模块 —— 这就是 "通用模板 + 分渠道定义" 的解耦。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from finance.crawler.fields import map_rows
from finance.crawler.fetchers import get_fetcher
from finance.lance.store import get_store, json_dumps
from finance.lance.schema import RECORD_COLS

# 标准字段 -> 落库字段 (同名列)
STD_TO_COL = {c: c for c in RECORD_COLS}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_id(channel_id: str, instrument_id: str, ts: str | None,
              trade_type: str | None = None, hash_suffix: str | None = None) -> str:
    base = f"{channel_id}:{instrument_id}:{ts or ''}:{trade_type or ''}"
    if hash_suffix:
        base += f":{hash_suffix}"
    return base


def load_channel_context(store, channel_id: str) -> dict:
    """读取渠道上下文: 渠道定义 + 列定义 + 各级参数 (全部来自 LanceDB)。"""
    from finance.lance.registry import ChannelRegistry

    ch = store.get("channels", "channel_id", channel_id)
    if not ch:
        raise KeyError(f"渠道未注册: {channel_id}")
    # 列定义
    col_defs = store.query("column_defs", where=f"channel_id = '{channel_id}'")
    # 参数: channel 级 (已反序列化)
    params = ChannelRegistry(store).param_dict(channel_id, scope="channel")
    return {"channel": ch, "column_defs": col_defs, "params": params}


def channel_instrument_defaults(channel_id: str, instrument_id: str, store=None) -> dict:
    """渠道×品种级参数 (LanceDB params 表 scope=instrument)。"""
    from finance.lance.registry import ChannelRegistry
    store = store or get_store()
    rows = ChannelRegistry(store).get_params(channel_id, scope="instrument")
    out = {}
    for p in rows:
        if p.get("key") and p.get("instrument_id") == instrument_id:
            from finance.lance.registry import _deserialize_param
            out[p["key"]] = _deserialize_param(p.get("value"), p.get("value_type"))
    return out


def fetch_channel(channel_id: str, instrument_id: str | None = None,
                  time_level: str | None = None, trade_type: str | None = None,
                  force: bool = False, verbose: bool = False, store=None) -> dict:
    """执行一个渠道的获取 (可限定品种), 返回落库结果摘要。"""
    store = store or get_store()
    t0 = time.time()
    try:
        ctx = load_channel_context(store, channel_id)
    except KeyError as e:
        return {"ok": False, "error": str(e), "channel_id": channel_id}

    ch = ctx["channel"]
    col_defs = ctx["column_defs"]
    channel_params = ctx["params"]
    instruments = _resolve_instruments(channel_id, instrument_id, ch)

    total_records = 0
    errors = []
    results = []
    for inst in instruments:
        inst_params = channel_instrument_defaults(channel_id, inst)
        payload = {
            "channel_id": channel_id,
            "channel": ch,
            "instrument_id": inst,
            "instrument": inst,
            "time_level": time_level,
            "trade_type": trade_type,
            "params": {**channel_params, **inst_params},
            "force": force,
        }
        # 1) 分渠道 fetcher (自定义逻辑)
        fn = get_fetcher(channel_id)
        if fn is not None:
            try:
                res = fn(store, payload)
                if not isinstance(res, dict):
                    res = {"ok": False, "error": "fetcher 返回类型错误"}
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        else:
            # 2) 通用引擎降级: 用 CrawlerBase + 渠道 params 里的 url/method
            res = _generic_fetch(payload, ch)
        # 3) 字段映射 + 落库
        raw_rows = res.get("raw_rows", []) or []
        mapped = map_rows(raw_rows, col_defs, default_ts_col=_default_ts_col(ch))
        saved = _save_records(store, channel_id, inst, time_level, trade_type, mapped, ch)
        total_records += saved
        summary = {
            "instrument_id": inst,
            "ok": res.get("ok", True) and res.get("error") is None,
            "raw_rows": len(raw_rows),
            "mapped_rows": len(mapped),
            "saved_records": saved,
            "error": res.get("error"),
            "demo": res.get("demo", False),
            "detail": res.get("detail"),
        }
        results.append(summary)
        if summary["error"]:
            errors.append(f"{inst}: {summary['error']}")

    status = "ok" if not errors else ("partial" if results else "failed")
    message = f"渠道 {channel_id} 获取完成: {total_records} 条记录" if not errors else \
        f"渠道 {channel_id} 部分失败: {'; '.join(errors[:3])}"
    logger = _logger(store)
    logger.log("fetch", status=status, message=message, channel_id=channel_id,
               rows_count=total_records, duration_ms=int((time.time() - t0) * 1000),
               detail={"results": results, "instrument_count": len(instruments)})
    # 更新渠道 last_run
    store.upsert("channels", [{
        "channel_id": channel_id, "last_run_at": _now(), "last_status": status,
    }], "channel_id")
    return {
        "ok": status != "failed", "status": status,
        "channel_id": channel_id, "instruments": instruments,
        "results": results, "total_records": total_records,
        "errors": errors, "duration_ms": int((time.time() - t0) * 1000),
    }


def _resolve_instruments(channel_id: str, instrument_id: str | None, ch: dict) -> list[str]:
    """确定本次要抓的品种列表。"""
    if instrument_id:
        return [instrument_id]
    # 渠道 params 里的 instruments 参数优先
    if ch.get("params") and isinstance(ch["params"], dict):
        insts = ch["params"].get("instruments")
        if insts:
            return insts if isinstance(insts, list) else [str(insts)]
    return ch.get("instruments") or [""]


def _default_ts_col(ch: dict) -> str | None:
    """渠道默认时间列 (column_defs 未显式映射 ts 时兜底)。"""
    if ch.get("params") and isinstance(ch["params"], dict):
        v = ch["params"].get("default_ts_col")
        if v:
            return str(v)
    return None


def _generic_fetch(payload: dict, ch: dict) -> dict:
    """通用引擎降级: 渠道定义 url/method + params 驱动 CrawlerBase。"""
    from finance.crawler.base import CrawlerBase

    url = payload["params"].get("url") or ch.get("source")
    if not url:
        return {"ok": False, "error": "无 url (需要自定义 fetcher 或配置 url 参数)"}
    crawler = CrawlerBase(channel_id=payload["channel_id"], params=payload["params"])
    rows = crawler.run()
    return {"ok": True, "raw_rows": rows, "demo": False}


def _save_records(store, channel_id: str, instrument_id: str, time_level: str | None,
                  trade_type: str | None, mapped: list[dict], ch: dict) -> int:
    """标准行 -> data_records 表 (record_id 去重, 落库时补渠道上下文列)。"""
    rows = []
    for m in mapped:
        std = m["mapped"]
        ts = std.get("ts")
        if not ts:
            ts = _now()
        raw = m.get("raw", {})
        rid = record_id(channel_id, instrument_id, str(ts)[:10] if time_level in ("1d", "1w", "1M") else str(ts),
                        trade_type, _hash(raw))
        rows.append({
            "record_id": rid,
            "channel_id": channel_id,
            "instrument_id": instrument_id,
            "instrument_name": std.get("instrument_name") or _inst_name(instrument_id),
            "data_class": _to_str(std.get("data_class") or ch.get("data_classes") or ""),
            "region": _to_str(std.get("region") or ch.get("regions") or ""),
            "exchange": _to_str(std.get("exchange") or ch.get("exchanges") or ""),
            "time_level": time_level or "",
            "trade_type": trade_type or "",
            "ts": ts,
            "open": std.get("open"), "high": std.get("high"), "low": std.get("low"),
            "close": std.get("close"), "volume": std.get("volume"), "amount": std.get("amount"),
            "title": std.get("title"), "link": std.get("link"), "content": std.get("content"),
            "value": std.get("value"),
            "raw": json_dumps(raw),
            "extra": json_dumps({k: v for k, v in std.items()
                                 if k not in ("ts", "open", "high", "low", "close",
                                              "volume", "amount", "title", "link",
                                              "content", "value")}),
            "source_meta": json_dumps({"script": ch.get("script"), "version": ch.get("name_en")}),
            "created_at": _now(),
        })
    if rows:
        store.upsert("data_records", rows, "record_id")
    return len(rows)


def _hash(raw: dict) -> str:
    import hashlib
    s = json_dumps(raw)
    return hashlib.md5(s.encode()).hexdigest()[:8]


def _inst_name(instrument_id: str) -> str:
    try:
        from finance.taxonomy import load_taxonomy
        tax = load_taxonomy()
        inst = tax.resolve_instrument(instrument_id)
        if inst:
            return inst.get("name", instrument_id)
    except Exception:
        pass
    return instrument_id


def _to_str(v) -> str:
    """list/dict 转字符串 (LanceDB string 列不能存 list)。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    if isinstance(v, dict):
        return json_dumps(v)
    return str(v)


def _logger(store):
    from finance.lance.logs import RunLogger
    return RunLogger(store)


# ---------- 查询数据 ----------
def query_records(store=None, channel_id: str | None = None, instrument_id: str | None = None,
                  limit: int = 100, where: str | None = None, order_by: str = "created_at") -> list[dict]:
    store = store or get_store()
    conds = []
    if channel_id:
        conds.append(f"channel_id = '{channel_id}'")
    if instrument_id:
        conds.append(f"instrument_id = '{instrument_id}'")
    if where:
        conds.append(where)
    w = " AND ".join(conds) if conds else None
    return store.query("data_records", where=w, limit=limit, order_by=order_by)


def records_stats(store=None) -> dict:
    store = store or get_store()
    rows = store.all("data_records", limit=100000) if store.count("data_records") <= 100000 \
        else store.query("data_records", limit=100000)
    by_channel: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_instrument: dict[str, int] = {}
    for r in rows:
        c = r.get("channel_id") or "?"
        by_channel[c] = by_channel.get(c, 0) + 1
        dc = r.get("data_class") or "?"
        by_class[dc] = by_class.get(dc, 0) + 1
        iid = r.get("instrument_id") or "?"
        by_instrument[iid] = by_instrument.get(iid, 0) + 1
    return {
        "total": len(rows),
        "by_channel": by_channel,
        "by_data_class": by_class,
        "by_instrument": by_instrument,
    }
