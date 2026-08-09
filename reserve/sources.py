"""reserve/sources.py — 数据源管理器 (多源每日信息聚合).

回答 ISSUE #5 核心诉求: "站点和获取方式会持续增加, 需要一个管理器"。

职责:
  1. 适配器注册表视图 (哪些源可用 / 各自类别 / 是否启用)
  2. 多源拉取调度 (pipeline/adapters.fetch_all) + 缓存
  3. 聚合摘要 digest: 按类别 (repos/papers/news/tech/prediction) 汇总成
     「科技人每日信息」结构化视图, 供 Web 页与 REST API 使用
  4. 数据源管理: 增删/启停/配置 (config/sources.json, 热更新)

类别映射 (与 Web「每日聚合」页签一致):
  repos      -> 开源项目 (CNB + GitHub)
  papers     -> 新论文 (arXiv)
  news       -> 热点信息 (Hacker News 等)
  tech       -> 科技进展 (RSS/订阅源)
  prediction -> 预测市场 (Polymarket, 风险对冲信号)

用法:
  python -m reserve.sources --list           # 查看数据源
  python -m reserve.sources --fetch          # 拉取全部启用源 (写缓存)
  python -m reserve.sources --fetch cnb      # 只拉 CNB
  python -m reserve.sources --digest         # 生成聚合摘要 (读缓存)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pipeline.adapters import registry, fetch_all, fetch_one

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "pipeline" / "data" / "sources"
CONFIG_PATH = ROOT / "config" / "sources.json"

# 类别展示顺序与中文名
CATEGORIES = [
    ("repos", "开源项目"),
    ("papers", "新论文"),
    ("news", "热点信息"),
    ("tech", "科技进展"),
    ("prediction", "预测市场"),
]


def load_config() -> dict:
    """读取数据源管理器配置 (热更新: 每次调用重新读盘)。"""
    if not CONFIG_PATH.exists():
        return {"sources": {}, "defaults": {}}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[sources] 配置解析失败 {CONFIG_PATH}: {e}", file=sys.stderr)
        return {"sources": {}, "defaults": {}}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_sources() -> dict:
    """数据源管理器视图: 适配器注册表 + 启用状态 + 配置摘要 + 最近拉取。"""
    cfg = load_config()
    defaults = cfg.get("defaults", {})
    src_cfg = cfg.get("sources", {})

    sources = []
    for a in registry.list_adapters():
        sc = src_cfg.get(a["id"], {})
        enabled = sc.get("enabled", defaults.get("enabled", True))
        cache = CACHE_DIR / f"{a['id']}.json"
        fetched_at = None
        count = 0
        if cache.exists():
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
                fetched_at = payload.get("fetched_at")
                count = payload.get("count", 0)
            except Exception:
                pass
        sources.append({
            "id": a["id"],
            "name": a["name"],
            "category": a["category"],
            "description": a["description"],
            "enabled": bool(enabled),
            "config": {k: v for k, v in sc.items() if k != "enabled"},
            "cached_at": fetched_at,
            "cached_count": count,
        })
    return {
        "mode": "sources",
        "total": len(sources),
        "enabled": sum(1 for s in sources if s["enabled"]),
        "items": sources,
    }


def digest(items: list[dict] | None = None, refresh: bool = False,
           only: list[str] | None = None) -> dict:
    """聚合摘要: 读缓存 (或强制 refresh 拉取), 按类别分组。

    返回结构 (供 /api/v1/digest 与 Web「每日聚合」页签):
      {
        "mode": "digest",
        "generated_at": ...,
        "sources": [{"id","name","category","count","ok"}...],
        "categories": [{"key","label","count","items":[...]}...],
        "total": N
      }
    """
    if refresh:
        results = fetch_all(only=only, write_cache=True)
    else:
        results = []
        for sid in registry.list_ids():
            cache = CACHE_DIR / f"{sid}.json"
            if cache.exists():
                try:
                    payload = json.loads(cache.read_text(encoding="utf-8"))
                    results.append({
                        "source": sid, "ok": True,
                        "count": payload.get("count", 0),
                        "items": payload.get("items", []),
                    })
                except Exception:
                    results.append({"source": sid, "ok": False, "count": 0, "items": []})
            else:
                results.append({"source": sid, "ok": False, "count": 0, "items": []})

    by_source = {}
    for r in results:
        by_source[r["source"]] = r

    # 全部 item 按类别分组
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        for it in r.get("items", []):
            cat = it.get("category") or "other"
            grouped[cat].append(it)

    cat_out = []
    for key, label in CATEGORIES:
        its = grouped.get(key, [])
        its.sort(key=lambda x: x.get("score") or 0, reverse=True)
        cat_out.append({"key": key, "label": label, "count": len(its), "items": its[:50]})

    # 其他未归类
    others = grouped.get("other", [])
    if others:
        cat_out.append({"key": "other", "label": "其他", "count": len(others),
                        "items": others[:50]})

    source_meta = {a["id"]: a for a in registry.list_adapters()}
    sources_out = [
        {
            "id": sid,
            "name": source_meta.get(sid, {}).get("name", sid),
            "category": source_meta.get(sid, {}).get("category", ""),
            "ok": r.get("ok", False),
            "count": r.get("count", 0),
            "error": r.get("error"),
        }
        for sid, r in sorted(by_source.items())
    ]

    return {
        "mode": "digest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": sum(r.get("count", 0) for r in results),
        "sources": sources_out,
        "categories": cat_out,
    }


# ============================================================
# 数据源管理 (增删/启停/配置) —— config/sources.json 热更新
# ============================================================

def set_enabled(source_id: str, enabled: bool) -> dict:
    cfg = load_config()
    cfg.setdefault("sources", {})
    sc = cfg["sources"].setdefault(source_id, {})
    sc["enabled"] = enabled
    save_config(cfg)
    return {"source": source_id, "enabled": enabled, "ok": True}


def set_config(source_id: str, patch: dict) -> dict:
    cfg = load_config()
    cfg.setdefault("sources", {})
    sc = cfg["sources"].setdefault(source_id, {})
    for k, v in patch.items():
        sc[k] = v
    save_config(cfg)
    return {"source": source_id, "updated": list(patch.keys()), "ok": True}


def add_feed(name: str, url: str, category: str = "tech") -> dict:
    """新增 RSS 订阅源 (数据源管理器的最常见操作)。"""
    cfg = load_config()
    cfg.setdefault("sources", {})
    rss = cfg["sources"].setdefault("rss", {})
    feeds = rss.setdefault("feeds", [])
    # 去重
    for f in feeds:
        if f.get("url") == url:
            return {"source": "rss", "ok": True, "already_exists": True, "feed": f}
    feed = {"name": name, "url": url, "category": category}
    feeds.append(feed)
    save_config(cfg)
    return {"source": "rss", "ok": True, "already_exists": False, "feed": feed}


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="多源数据管理器")
    parser.add_argument("--list", action="store_true", help="查看数据源")
    parser.add_argument("--fetch", nargs="*", default=None, help="拉取全部源 (或指定源)")
    parser.add_argument("--digest", action="store_true", help="生成聚合摘要")
    parser.add_argument("--enable", metavar="SOURCE", help="启用某源")
    parser.add_argument("--disable", metavar="SOURCE", help="停用某源")
    parser.add_argument("--add-feed", nargs=3, metavar=("NAME", "URL", "CATEGORY"),
                        help="新增 RSS 订阅源")
    parser.add_argument("--out", default=None, help="输出 JSON 到文件")
    args = parser.parse_args()

    data = None
    if args.list:
        data = list_sources()
    elif args.fetch is not None:
        only = args.fetch if args.fetch else None
        results = fetch_all(only=only, write_cache=True)
        ok = sum(1 for r in results if r["ok"])
        print(f"[sources] 拉取完成: {ok}/{len(results)} 源成功")
        data = {"results": results}
    elif args.digest:
        data = digest()
    elif args.enable:
        data = set_enabled(args.enable, True)
    elif args.disable:
        data = set_enabled(args.disable, False)
    elif args.add_feed:
        name, url, category = args.add_feed
        data = add_feed(name, url, category)
    else:
        parser.print_help()
        return 1

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                                  encoding="utf-8")
        print(f"[sources] wrote {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
