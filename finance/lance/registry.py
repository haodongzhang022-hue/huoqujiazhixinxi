"""finance/lance/registry.py —— 渠道注册表 (channels / column_defs / params 三表统一管理)。

职责:
  - 渠道注册: 新增/更新/启用/停用/删除渠道 (channels 表)
  - 列定义: 渠道列 -> 标准字段 (column_defs 表)
  - 参数: 渠道/品种/获取器/请求/存储/调度 各级参数 (params 表)
  - 种子初始化: 从 config/finance/catalog.json + taxonomy.json 迁移现有 8 数据源/28 品种
  - 挖掘转正: discovery_candidates -> channels + column_defs + params 一键转正
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from finance.lance.store import get_store, json_dumps

SCOPES = ("channel", "instrument", "fetcher", "request", "storage", "schedule", "feature")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChannelRegistry:
    def __init__(self, store=None):
        self.store = store or get_store()

    # ============ 渠道 (channels) ============
    def register_channel(self, channel: dict, upsert_key: str = "channel_id") -> str:
        """注册/更新渠道。"""
        ch = dict(channel)
        ch.setdefault("channel_id", ch.get("id") or "")
        ch.setdefault("status", "active")
        ch.setdefault("enabled", True)
        now = _now()
        ch.setdefault("created_at", now)
        ch["updated_at"] = now
        # JSON 字段序列化
        for jf in ("data_classes", "regions", "exchanges", "auth", "storage",
                   "schedule", "disclosure", "requires", "fetchers", "params"):
            if jf in ch and not isinstance(ch[jf], str):
                ch[jf] = json_dumps(ch[jf])
        if not ch.get("channel_id"):
            raise ValueError("channel_id 必填")
        self.store.upsert("channels", [ch], upsert_key)
        return ch["channel_id"]

    def get_channel(self, channel_id: str) -> dict | None:
        return self.store.get("channels", "channel_id", channel_id)

    def list_channels(self, status: str | None = None) -> list[dict]:
        where = f"status = '{status}'" if status else None
        return self.store.query("channels", where=where, order_by="channel_id")

    def enable(self, channel_id: str, enabled: bool = True):
        self.store.upsert("channels", [{"channel_id": channel_id, "enabled": enabled,
                                        "updated_at": _now()}], "channel_id")

    def delete_channel(self, channel_id: str):
        self.store.delete("channels", f"channel_id = '{channel_id}'")

    # ============ 列定义 (column_defs) ============
    def add_column_def(self, channel_id: str, source_col: str, standard_col: str,
                       col_type: str = "string", description: str = "",
                       cleaning: dict | None = None, required: bool = False,
                       enabled: bool = True, params: dict | None = None):
        now = _now()
        row = {
            "channel_id": channel_id,
            "source_col": source_col,
            "standard_col": standard_col,
            "col_type": col_type,
            "description": description,
            "cleaning": json_dumps(cleaning or {}),
            "required": required,
            "enabled": enabled,
            "params": json_dumps(params or {}),
            "created_at": now,
            "updated_at": now,
            "ts": now,
        }
        # column_defs 业务主键为 (channel_id, source_col), 用 delete+add 实现 upsert
        self._upsert_col_def(row)
        return row

    def _upsert_col_def(self, row: dict):
        """column_defs 以 (channel_id, source_col) 为业务主键。"""
        t = self.store.table("column_defs")
        rows = self.store.query("column_defs",
                                where=f"channel_id = '{row['channel_id']}' AND source_col = '{row['source_col']}'")
        if rows:
            t.delete(f"channel_id = '{row['channel_id']}' AND source_col = '{row['source_col']}'")
        t.add([row])

    def set_column_defs(self, channel_id: str, defs: list[dict]):
        """批量设置渠道列定义 (全量覆盖)。defs: [{source_col, standard_col, col_type, cleaning, description}]"""
        t = self.store.table("column_defs")
        try:
            t.delete(f"channel_id = '{channel_id}'")
        except Exception:
            pass
        for d in defs:
            self.add_column_def(channel_id, **d)

    def list_column_defs(self, channel_id: str | None = None) -> list[dict]:
        where = f"channel_id = '{channel_id}'" if channel_id else None
        return self.store.query("column_defs", where=where, order_by="channel_id")

    # ============ 参数 (params) ============
    def set_param(self, channel_id: str, key: str, value, scope: str = "channel",
                  description: str = "", instrument_id: str = ""):
        if scope not in SCOPES:
            raise ValueError(f"scope 必须是 {SCOPES} 之一")
        param_id = f"{channel_id}:{scope}:{key}"
        now = _now()
        row = {
            "param_id": param_id,
            "channel_id": channel_id,
            "scope": scope,
            "key": key,
            # value 统一存 JSON 字符串, 保证 LanceDB 列类型一致
            "value": json_dumps(value) if value is not None else "",
            "value_type": _value_type(value),
            "description": description,
            "instrument_id": instrument_id,
            "created_at": now,
            "updated_at": now,
        }
        self.store.upsert("params", [row], "param_id")
        return param_id

    def get_params(self, channel_id: str, scope: str | None = None) -> list[dict]:
        where = f"channel_id = '{channel_id}'"
        if scope:
            where += f" AND scope = '{scope}'"
        return self.store.query("params", where=where)

    def param_dict(self, channel_id: str, scope: str | None = None) -> dict:
        """参数 -> dict (value 已反序列化)。"""
        out = {}
        for p in self.get_params(channel_id, scope):
            key = p.get("key")
            if key:
                out[key] = _deserialize_param(p.get("value"), p.get("value_type"))
        return out

    def delete_param(self, channel_id: str, key: str, scope: str = "channel"):
        self.store.delete("params", f"param_id = '{channel_id}:{scope}:{key}'")

    # ============ 种子初始化 ============
    def seed_from_catalog(self) -> dict:
        """从 config/finance/catalog.json + taxonomy.json 迁移现有数据源 -> channels/column_defs/params。

        返回: {"channels": n, "column_defs": n, "params": n, "errors": [...]}
        """
        from finance.catalog import load_catalog
        from finance.taxonomy import load_taxonomy

        cat = load_catalog()
        tax = load_taxonomy()
        result = {"channels": 0, "column_defs": 0, "params": 0, "errors": []}
        for s in cat.sources:
            cid = s["id"]
            ch = {
                "channel_id": cid,
                "name": s.get("name", cid),
                "name_en": s.get("name_en", cid),
                "kind": s.get("type", "python_lib"),
                "data_classes": s.get("coverage", {}).get("data_classes", []),
                "regions": s.get("coverage", {}).get("regions", []),
                "exchanges": s.get("coverage", {}).get("exchanges", []),
                "status": "active",
                "source": s.get("source", ""),
                "method": s.get("type", ""),
                "script": s.get("script", ""),
                "module": s.get("module", ""),
                "command": s.get("command", ""),
                "auth": s.get("requires", {}),
                "rate_limit": "",
                "storage": s.get("storage", {}),
                "schedule": s.get("schedule", {}),
                "disclosure": s.get("disclosure", {}),
                "requires": s.get("requires", {}),
                "fetchers": s.get("fetchers", []),
                "enabled": True,
                "discovered_from": "seed_catalog",
            }
            try:
                self.register_channel(ch)
                result["channels"] += 1
            except Exception as e:  # noqa: BLE001
                result["errors"].append(f"{cid}: {e}")
            # 列定义: 根据 fetcher 输出类型推断标准列
            defs = _infer_column_defs(s)
            for d in defs:
                try:
                    self.add_column_def(cid, **d)
                    result["column_defs"] += 1
                except Exception as e:  # noqa: BLE001
                    result["errors"].append(f"{cid} col {d.get('source_col')}: {e}")
            # 渠道级参数
            for k, v in (s.get("params") or {}).items():
                self.set_param(cid, k, v, scope="channel")
                result["params"] += 1
        # 品种级参数: 为 taxonomy 品种生成 instrument 级 symbol 参数 (akshare/yfinance/ccxt)
        inst_map = _instrument_symbol_map()
        for iid, data in inst_map.items():
            for cid, symbol in data.items():
                ch = self.get_channel(cid)
                if not ch:
                    continue
                self.set_param(cid, "symbol", symbol, scope="instrument",
                               description=f"{iid} -> {cid} 的 symbol",
                               instrument_id=iid)
                result["params"] += 1
        return result


# ============ 工具函数 ============

def _value_type(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, (list, dict)):
        return "json"
    return "string"


def _deserialize_param(value, value_type: str = "string"):
    """params.value 反序列化 (统一存 JSON 字符串)。"""
    if value is None:
        return None
    if value_type == "json":
        try:
            return json.loads(value)
        except Exception:
            return value
    if value_type == "bool":
        return str(value).lower() in ("true", "1")
    if value_type == "number":
        try:
            return float(value) if "." in str(value) else int(value)
        except (ValueError, TypeError):
            return value
    return value


def _infer_column_defs(source: dict) -> list[dict]:
    """根据数据源 fetcher 输出类型推断标准列定义 (可后续人工覆盖)。"""
    defs = []
    outputs = {f.get("output") for f in source.get("fetchers", []) if f.get("output")}
    # 日期列
    defs.append({"source_col": "date", "standard_col": "ts", "col_type": "datetime",
                 "description": "日期/时间", "cleaning": None, "required": False})
    if "ohlcv" in outputs:
        for src, std in (("open", "open"), ("high", "high"), ("low", "low"),
                         ("close", "close"), ("volume", "volume"), ("amount", "amount"),
                         ("成交额", "amount"), ("成交量", "volume"), ("开盘", "open"),
                         ("最高", "high"), ("最低", "low"), ("收盘", "close")):
            defs.append({"source_col": src, "standard_col": std, "col_type": "float",
                         "description": std, "cleaning": None, "required": False})
    if "news" in outputs or source.get("type") == "rss":
        for src, std, ct in (("title", "title", "string"), ("link", "link", "string"),
                             ("description", "content", "string"),
                             ("pubDate", "ts", "datetime"),
                             ("summary", "content", "string"),
                             ("headline", "title", "string"), ("url", "link", "string")):
            defs.append({"source_col": src, "standard_col": std, "col_type": ct,
                         "description": std, "cleaning": None, "required": False})
    if "macro_series" in outputs or "net_value" in outputs:
        for src, std, ct in (("value", "value", "float"), ("指标", "value", "float"),
                             ("数值", "value", "float"), ("今值", "value", "float"),
                             ("单位净值", "value", "float")):
            defs.append({"source_col": src, "standard_col": std, "col_type": ct,
                         "description": std, "cleaning": None, "required": False})
    return defs


def _instrument_symbol_map() -> dict:
    """品种 id -> {渠道: symbol} (可后续通过 params 表覆盖)。"""
    m = {}
    stock = {
        "SH600000": {"akshare": "600000", "yfinance": "600000.SS"},
        "SH510300": {"akshare": "510300", "yfinance": "510300.SS"},
        "HK00700": {"akshare": "00700", "yfinance": "0700.HK"},
        "US.AAPL": {"yfinance": "AAPL"},
        "US.SPY": {"yfinance": "SPY"},
        "JP.7203": {"yfinance": "7203.T"},
        "KR.005930": {"yfinance": "005930.KS"},
    }
    futures = {
        "CN.RB": {"akshare": "RB0"},
        "CN.CU": {"akshare": "CU0"},
        "CN.IF": {"akshare": "IF0"},
        "US.CL": {"yfinance": "CL=F"},
        "US.GC": {"yfinance": "GC=F"},
        "UK.LME.CU": {},
    }
    forex = {
        "FX.USDCNY": {"yfinance": "CNY=X", "akshare": "USDCNY"},
        "FX.EURUSD": {"yfinance": "EURUSD=X"},
        "FX.USDJPY": {"yfinance": "JPY=X"},
    }
    crypto = {
        "CRYPTO.BTC": {"ccxt": "BTC/USDT"},
        "CRYPTO.ETH": {"ccxt": "ETH/USDT"},
        "CRYPTO.SOL": {"ccxt": "SOL/USDT"},
    }
    macro = {
        "MACRO.US.CPI": {"fred": "CPIAUCSL"},
        "MACRO.US.FEDRATE": {"fred": "DFF"},
        "MACRO.US.UNRATE": {"fred": "UNRATE"},
    }
    for d in (stock, futures, forex, crypto, macro):
        m.update(d)
    return m
