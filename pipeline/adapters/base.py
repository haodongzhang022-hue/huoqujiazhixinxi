"""pipeline/adapters/base.py — 适配器基类 + 注册表 + 归一化。

统一数据模型 (item):
  {
    "source": "cnb" | "github" | "arxiv" | "hackernews" | "polymarket" | "rss",
    "item_id": "唯一ID (来源内去重)",
    "title": "标题",
    "url": "原文链接",
    "summary": "摘要/描述",
    "published_at": "ISO 时间",
    "category": "预分类 (repos/papers/news/tech/prediction)",
    "tags": ["标签..."],
    "score": 热度/重要性分数 (int/float, 越大越重要),
    "extra": {},   # 来源特有附加字段 (如 stars / 市场成交量)
    "raw": {},     # 原始响应 (调试/审计用, 可选)
  }

设计要点:
  - 每个适配器只做「拉取 + 解析 → item 列表」, 不做持久化;
  - 失败时抛 AdapterError, 由 fetch_all 捕获并汇总 (单源失败不影响整体);
  - 归一化字段统一由 normalize_item 完成, 适配器只需给语义字段。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "pipeline" / "data" / "sources"

# 全局注册表: {adapter_id: Adapter 类}
_REGISTRY: dict[str, type["Adapter"]] = {}


class AdapterError(Exception):
    """适配器执行失败 (网络/解析/配置)。"""


class Adapter:
    """数据源适配器基类。子类需实现 fetch() 返回 list[dict] (item 或裸语义字段)。"""

    id = "base"
    name = "基础适配器"
    category = "other"                 # repos / papers / news / tech / prediction
    description = ""
    # 配置读取路径 (config/sources.json -> sources.<id>)
    config = None

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    # ---- 子类覆写 ----
    def fetch(self) -> list[dict]:
        raise NotImplementedError

    # ---- 工具方法 ----
    @staticmethod
    def http_get(url: str, timeout: int = 20, headers: dict | None = None,
                 max_bytes: int = 10 * 1024 * 1024) -> bytes:
        """标准库 GET, 带 UA + 超时 + 大小上限。"""
        req = urllib.request.Request(url, headers={
            "User-Agent": "huoqujiazhixinxi-adapter/0.1",
            "Accept": "application/json, text/plain, */*",
            **(headers or {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(max_bytes + 1)[:max_bytes]
        except urllib.error.HTTPError as e:
            raise AdapterError(f"HTTP {e.code} {url}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise AdapterError(f"网络错误 {url}: {e}") from e

    @staticmethod
    def http_json(url: str, timeout: int = 20, headers: dict | None = None) -> dict | list:
        raw = Adapter.http_get(url, timeout=timeout, headers=headers)
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise AdapterError(f"JSON 解析失败: {url}: {e}") from e

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


class Registry:
    """适配器注册表 + 拉取调度。"""

    def register(self, cls: type[Adapter]):
        _REGISTRY[cls.id] = cls
        return cls

    def get(self, adapter_id: str) -> Adapter:
        if adapter_id not in _REGISTRY:
            raise KeyError(f"未知适配器: {adapter_id} (可用: {self.list_ids()})")
        return _REGISTRY[adapter_id]()

    def list_ids(self) -> list[str]:
        return sorted(_REGISTRY)

    def list_adapters(self) -> list[dict]:
        return [
            {"id": c.id, "name": c.name, "category": c.category, "description": c.description}
            for c in sorted(_REGISTRY.values(), key=lambda c: c.id)
        ]


registry = Registry()


def normalize_item(item: dict, source: str | None = None, fallback_id: str = "") -> dict:
    """归一化适配器返回的条目为统一 item 结构。"""
    src = source or item.get("source") or item.get("adapter") or "unknown"
    iid = item.get("item_id") or item.get("id") or item.get("guid") or fallback_id
    if not iid:
        iid = f"{src}-{hash(item.get('title', '')):x}"
    published = item.get("published_at") or item.get("published") or item.get("date") or item.get("created_at")
    return {
        "source": src,
        "item_id": str(iid),
        "title": str(item.get("title") or item.get("name") or item.get("headline") or "(无标题)"),
        "url": str(item.get("url") or item.get("link") or item.get("html_url") or item.get("web_url") or ""),
        "summary": str(item.get("summary") or item.get("description") or item.get("abstract") or ""),
        "published_at": published or Adapter.now(),
        "category": item.get("category") or _guess_category(src),
        "tags": [str(t) for t in (item.get("tags") or [])],
        "score": float(item.get("score") or item.get("stars") or item.get("heat") or 0),
        "extra": item.get("extra") or {},
        "raw": item.get("raw") or {},
    }


def _guess_category(source: str) -> str:
    return {
        "cnb": "repos", "github": "repos",
        "arxiv": "papers", "hackernews": "news",
        "polymarket": "prediction", "rss": "tech",
    }.get(source, "other")


def _load_sources_config() -> dict:
    """读取 config/sources.json (数据源管理器配置)。"""
    p = ROOT / "config" / "sources.json"
    if not p.exists():
        return {"sources": {}, "defaults": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[sources] 配置解析失败 {p}: {e}", file=sys.stderr)
        return {"sources": {}, "defaults": {}}


def _write_cache(source: str, items: list[dict]) -> Path:
    """写缓存 pipeline/data/sources/<source>.json (供展示/离线)。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{source}.json"
    payload = {
        "source": source,
        "fetched_at": Adapter.now(),
        "count": len(items),
        "items": items,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def fetch_one(adapter_id: str, config: dict | None = None,
              write_cache: bool = True, quiet: bool = False) -> dict:
    """拉取单个数据源并写缓存。返回 {source, ok, count, items, cache, error?}。"""
    cls = _REGISTRY.get(adapter_id)
    if cls is None:
        return {"source": adapter_id, "ok": False, "count": 0, "items": [],
                "error": f"未知适配器: {adapter_id}"}
    try:
        inst = cls(config or {})
        raw_items = inst.fetch()
        items = [normalize_item(it, source=adapter_id, fallback_id=f"{adapter_id}-{i}")
                 for i, it in enumerate(raw_items)]
        # 去重 (按 item_id)
        seen: set[str] = set()
        uniq = []
        for it in items:
            if it["item_id"] in seen:
                continue
            seen.add(it["item_id"])
            uniq.append(it)
        cache = str(_write_cache(adapter_id, uniq)) if write_cache else None
        if not quiet:
            print(f"[sources] {adapter_id}: {len(uniq)} 条 -> {cache}")
        return {"source": adapter_id, "ok": True, "count": len(uniq),
                "items": uniq, "cache": cache}
    except AdapterError as e:
        if not quiet:
            print(f"[sources] {adapter_id}: ❌ {e}", file=sys.stderr)
        return {"source": adapter_id, "ok": False, "count": 0, "items": [], "error": str(e)}
    except Exception as e:
        if not quiet:
            print(f"[sources] {adapter_id}: ❌ 未预期异常 {e}", file=sys.stderr)
        return {"source": adapter_id, "ok": False, "count": 0, "items": [], "error": str(e)}


def fetch_all(only: list[str] | None = None, write_cache: bool = True,
              quiet: bool = False) -> list[dict]:
    """拉取全部启用的数据源 (config/sources.json -> enabled)。

    单源失败不影响其他源; 返回每源结果列表。
    """
    cfg = _load_sources_config()
    defaults = cfg.get("defaults", {})
    sources_cfg = cfg.get("sources", {})

    enabled: list[str] = []
    for sid in _REGISTRY:
        sc = sources_cfg.get(sid, {})
        enabled_flag = sc.get("enabled", defaults.get("enabled", True))
        if enabled_flag and (only is None or sid in only):
            enabled.append(sid)

    results = []
    for sid in sorted(enabled):
        sc = {**defaults, **sources_cfg.get(sid, {})}
        results.append(fetch_one(sid, config=sc, write_cache=write_cache, quiet=quiet))
    return results
