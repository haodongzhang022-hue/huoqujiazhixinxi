"""reserve/feed.py — 人类优先 / AI 优先 信息流视图（对外信息流契约）。

设计哲学（对应 ISSUE #4 用户诉求）：
  「每天的开源项目获取和按功能分类，不该每个用户重复做一次，而是做一次让更多人直接获取；
    并且允许 AI 获取信息直接使用，方便搭建自动化流程。」

本模块把储备库/快照/质量/审核等内部数据统一整理为**两条对外信息流**：

  1. HumanFeed (人类优先)  —— 按生态分类分组、中文摘要 + 功能标签 + 使用场景 + 审核建议，
                              面向"科技人每日浏览"的场景，一眼看到"今天哪些项目对我有用"。
  2. AiFeed    (AI 优先)   —— 扁平、紧凑、机器友好：每条都是最小字段集合 + 可直接消费的
                              content 正文，AI/自动化流程拿到即可用（搭自动化、喂给 Agent）。

接口契约 (见 schemas.py):
  GET /api/v1/feed?mode=human|ai&date=YYYY-MM-DD&category=...&tag=...&decision=...
  GET /api/v1/feed/{date}?mode=...           # 指定日期的历史信息流
  GET /api/v1/sources                        # 数据源注册表（含预留扩展位）
  GET /api/v1/health                         # 服务健康
  GET /api/v1/sync/{source}                  # 预留: 单源手动同步（扩展数据源时实现）

扩展预留：用户将在后续 ISSUE 中提出「CNB 新项目 / 论文 / 热点 / 科技进展」的接入，
本模块的 Item 已用 type 字段预留 (repo/paper/trend/news/cnb-project)，
数据源表 (sources) 也已登记这些扩展位，届时只需实现对应 fetch 并归一化为 Item 即可汇入信息流。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from reserve.store import ReserveStore

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "pipeline" / "data" / "snapshots"
ITEM_PAGE_SIZE = 100

# 数据源注册表: 已接入 + 预留扩展位
SOURCES = [
    {
        "id": "github-repos",
        "label": "GitHub 开源项目",
        "description": "每日采集 GitHub 新/热开源项目 (MCP/Agent/RAG/AI 工具等 8 大生态分类)",
        "status": "active",
        "item_type": "repo",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/fetch.py + reserve/ingest.py 每日入库",
        "adapter": "github",
    },
    {
        "id": "cnb-projects",
        "label": "CNB 新项目",
        "description": "CNB 平台每日新增/活跃的开源项目 (ISSUE #5 已接入 cnb adapter)",
        "status": "active",
        "item_type": "cnb-project",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/adapters/cnb.py (cnb search list-public-repos)",
        "adapter": "cnb",
    },
    {
        "id": "papers",
        "label": "AI/科技论文",
        "description": "每日新论文 (ISSUE #5 已接入 arxiv adapter)",
        "status": "active",
        "item_type": "paper",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/adapters/arxiv.py (arXiv Atom API)",
        "adapter": "arxiv",
    },
    {
        "id": "tech-trends",
        "label": "热点与科技进展",
        "description": "科技热点 / 产品发布 / 研究进展 (ISSUE #5 已接入 hackernews + rss)",
        "status": "active",
        "item_type": "trend",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/adapters/hackernews.py + rss.py",
        "adapter": "hackernews",
    },
    {
        "id": "news",
        "label": "科技新闻",
        "description": "科技行业要闻 (ISSUE #5 已接入 rss adapter)",
        "status": "active",
        "item_type": "news",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/adapters/rss.py (通用 RSS/Atom)",
        "adapter": "rss",
    },
    {
        "id": "prediction",
        "label": "预测市场",
        "description": "Polymarket 等预测市场: 事件概率/成交量/走向信号 (ISSUE #5)",
        "status": "active",
        "item_type": "trend",
        "enabled": True,
        "planned": False,
        "note": "已接入: pipeline/adapters/polymarket.py (结构化行情, 单独对接见 docs/sources-extension.md §6)",
        "adapter": "polymarket",
    },
]

# 多源适配器缓存目录 (pipeline/data/sources/*.json, 由 reserve.sources 拉取)
SOURCES_CACHE_DIR = ROOT / "pipeline" / "data" / "sources"

# 生态分类 -> 人类可读中文名
CATEGORY_LABELS = {
    "mcp-servers": "MCP 服务器与工具",
    "ai-agents": "AI 代理框架",
    "rag-kb": "RAG 与知识库",
    "agent-orchestration": "Agent 编排与路由",
    "llm-prompts": "LLM 提示词与工作流",
    "ai-dev-tools": "AI 开发工具与 IDE",
    "data-infra": "数据与向量基础设施",
    "developer-tools": "开发者工具与开源库",
}


def _clean(obj):
    import numpy as np
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_to_item(r: dict) -> dict:
    """储备库记录 -> 统一 Item (repo 类)。"""
    review = r.get("review")
    if isinstance(review, str):
        try:
            review = json.loads(review)
        except Exception:
            review = None
    review_info = None
    if isinstance(review, dict):
        review_info = {
            "verdict": review.get("verdict"),
            "score": review.get("score"),
            "risks": review.get("risks") or [],
            "recommendation": review.get("recommendation"),
        }
    return {
        "id": f"github-repos:{r.get('full_name')}",
        "type": "repo",
        "source": "github-repos",
        "source_label": "GitHub 开源项目",
        "title": r.get("full_name") or "",
        "url": r.get("url") or "",
        "description": r.get("description") or "",
        "summary_zh": r.get("function_summary") or r.get("description_zh") or "",
        "language": r.get("language") or "",
        "stars": int(r.get("stars") or 0),
        "stars_delta_24h": r.get("stars_delta_24h"),
        "stars_delta_7d": r.get("stars_delta_7d"),
        "is_new": bool(r.get("is_new_this_week")),
        "category": r.get("category") or "",
        "category_decision": r.get("category_decision") or "",
        "function_tags": list(r.get("function_tags") or []),
        "use_case": r.get("use_case"),
        "review": review_info,
        "matched_needs": list(r.get("matched_needs") or []),
        "published_at": r.get("created_at") or "",
        "first_seen_at": r.get("first_seen_at") or "",
        "extra": {
            "topics": list(r.get("topics") or []),
            "license": r.get("license") or "",
            "review_status": r.get("review_status") or "",
            "index_source": r.get("index_source") or "",
            "decision_score": r.get("decision_score"),
            "decision_reason": r.get("decision_reason") or "",
        },
    }


def _repo_from_snapshot(raw: dict) -> dict:
    """快照里的原始仓库记录 -> Item 兼容 dict (供无储备库时的降级路径)。"""
    full_name = raw.get("full_name") or raw.get("repo_id") or ""
    review = raw.get("review")
    if isinstance(review, str):
        try:
            review = json.loads(review)
        except Exception:
            review = None
    review_info = None
    if isinstance(review, dict):
        review_info = {
            "verdict": review.get("verdict"),
            "score": review.get("score"),
            "risks": review.get("risks") or [],
            "recommendation": review.get("recommendation"),
        }
    return {
        "id": f"github-repos:{full_name}",
        "type": "repo",
        "source": "github-repos",
        "source_label": "GitHub 开源项目",
        "title": full_name,
        "url": raw.get("url") or raw.get("html_url") or "",
        "description": raw.get("description") or "",
        "summary_zh": raw.get("function_summary") or raw.get("description_zh") or "",
        "language": raw.get("language") or "",
        "stars": int(raw.get("stars", raw.get("stargazers_count", 0)) or 0),
        "stars_delta_24h": raw.get("stars_delta_24h"),
        "stars_delta_7d": raw.get("stars_delta_7d"),
        "is_new": bool(raw.get("is_new_this_week")),
        "category": raw.get("category") or "",
        "category_decision": raw.get("category_decision") or "",
        "function_tags": list(raw.get("function_tags") or []),
        "use_case": raw.get("use_case"),
        "review": review_info,
        "matched_needs": list(raw.get("matched_needs") or []),
        "published_at": raw.get("created_at") or "",
        "first_seen_at": raw.get("first_seen_at") or "",
        "extra": {
            "topics": list(raw.get("topics") or []),
            "license": (raw.get("license") or {}).get("spdx_id") if isinstance(raw.get("license"), dict) else raw.get("license"),
            "review_status": raw.get("review_status") or "",
            "index_source": raw.get("index_source") or "",
        },
    }


def _load_snapshot_items(date: str | None = None) -> list[dict]:
    """从快照 JSON 加载指定日期(默认最新)的仓库记录 -> Item 列表。"""
    date = date or _today()
    p = SNAPSHOT_DIR / f"{date}.json"
    if not p.exists():
        # 退而求其次: 最近一个快照
        snaps = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
        if not snaps:
            return []
        p = snaps[0]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw_items = []
    if isinstance(data, dict):
        raw_items = data.get("repos") or data.get("items") or []
    elif isinstance(data, list):
        raw_items = data
    return [_repo_from_snapshot(r) for r in raw_items if r.get("full_name") or r.get("repo_id")]


def list_sources() -> list[dict]:
    """数据源注册表（含实时 last_sync 信息, 各源已由 ISSUE #5 适配器接入）。"""
    out = []
    for s in SOURCES:
        s = dict(s)
        adapter_id = s.get("adapter")
        if adapter_id:
            cache = SOURCES_CACHE_DIR / f"{adapter_id}.json"
            if cache.exists():
                try:
                    d = json.loads(cache.read_text(encoding="utf-8"))
                    s["last_sync_at"] = d.get("fetched_at")
                    s["last_items"] = d.get("count", 0)
                except Exception:
                    pass
        elif s["id"] == "github-repos":
            snaps = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
            if snaps:
                try:
                    d = json.loads(snaps[0].read_text(encoding="utf-8"))
                    s["last_sync_at"] = d.get("generated_at") or d.get("date")
                    s["last_items"] = len(d.get("repos") or d.get("items") or [])
                    if s.get("status") == "active" and s["last_items"] == 0:
                        s["status"] = "error"
                except Exception:
                    pass
        out.append(s)
    return out


# 适配器 id -> 统一 Item 的 source/type/source_label (用于信息流归一化)
_ADAPTER_ITEM_META = {
    "cnb": ("cnb-projects", "cnb-project", "CNB 新项目"),
    "github": ("github-repos", "repo", "GitHub 开源项目"),
    "arxiv": ("papers", "paper", "AI/科技论文"),
    "hackernews": ("tech-trends", "trend", "热点与科技进展"),
    "polymarket": ("prediction", "trend", "预测市场"),
    "rss": ("news", "news", "科技新闻"),
}


def _adapter_to_item(it: dict) -> dict | None:
    """多源适配器 item (pipeline/data/sources/*.json) -> 统一 Item。"""
    adapter_id = it.get("source")
    meta = _ADAPTER_ITEM_META.get(adapter_id)
    if not meta:
        return None
    source, itype, label = meta
    extra = dict(it.get("extra") or {})
    title = it.get("title") or ""
    # repo 类: title 是 full_name/path
    if itype in ("repo", "cnb-project"):
        full_name = title
        url = it.get("url") or ""
    else:
        full_name = title
        url = it.get("url") or ""
    return {
        "id": f"{source}:{it.get('item_id') or title}",
        "type": itype,
        "source": source,
        "source_label": label,
        "title": title,
        "url": url,
        "description": it.get("summary") or "",
        "summary_zh": it.get("summary") or "",
        "language": extra.get("language") or "",
        "stars": int(extra.get("stars") or it.get("score") or 0),
        "stars_delta_24h": extra.get("stars_delta_24h"),
        "stars_delta_7d": extra.get("stars_delta_7d"),
        "is_new": bool(extra.get("is_new_this_week")),
        "category": it.get("category") or "",
        "category_decision": extra.get("category_decision") or "",
        "function_tags": list(it.get("tags") or []),
        "use_case": None,
        "review": None,
        "matched_needs": [],
        "published_at": it.get("published_at") or "",
        "first_seen_at": "",
        "extra": extra,
    }


def _load_adapter_items() -> list[dict]:
    """读取多源适配器缓存 (pipeline/data/sources/*.json) -> 统一 Item 列表。

    覆盖: cnb / github / arxiv / hackernews / polymarket / rss。
    缓存由 reserve.sources --fetch 或 POST /api/v1/sources/fetch 生成。
    优先级: LanceDB source_items 表 (ISSUE #5) > JSON 缓存。
    """
    # 优先读 LanceDB (数据已按时间/功能排布入库)
    try:
        store = ReserveStore()
        rows = store.items_query(limit=100000)
        if rows:
            return [_item_row_to_item(r) for r in rows]
    except Exception:
        pass

    items: list[dict] = []
    if not SOURCES_CACHE_DIR.exists():
        return items
    for cache in sorted(SOURCES_CACHE_DIR.glob("*.json")):
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            continue
        for raw in payload.get("items") or []:
            it = _adapter_to_item(raw)
            if it:
                items.append(it)
    return items


def _item_row_to_item(row: dict) -> dict:
    """LanceDB source_items 表行 -> 统一 Item (对齐 _adapter_to_item 输出)。"""
    adapter_id = row.get("source") or ""
    meta = _ADAPTER_ITEM_META.get(adapter_id)
    if not meta:
        return None
    source, itype, label = meta
    extra = dict(row.get("extra") or {})
    title = row.get("title") or ""
    return {
        "id": f"{source}:{row.get('item_id') or title}",
        "type": itype,
        "source": source,
        "source_label": label,
        "title": title,
        "url": row.get("url") or "",
        "description": row.get("summary") or "",
        "summary_zh": row.get("summary") or "",
        "language": extra.get("language") or "",
        "stars": int(extra.get("stars") or row.get("score") or 0),
        "stars_delta_24h": extra.get("stars_delta_24h"),
        "stars_delta_7d": extra.get("stars_delta_7d"),
        "is_new": bool(extra.get("is_new_this_week")),
        "category": row.get("category") or "",
        "category_decision": extra.get("category_decision") or "",
        "function_tags": list(row.get("tags") or []),
        "use_case": None,
        "review": None,
        "matched_needs": [],
        "published_at": row.get("published_at") or row.get("date") or "",
        "first_seen_at": row.get("first_seen_at") or "",
        "extra": extra,
    }


def build_human_feed(items: list[dict], date: str, limit: int = 50,
                     offset: int = 0, category: str | None = None,
                     decision: str | None = None) -> dict:
    """人类优先信息流: 按生态分类分组 + 中文摘要 + 标签 + 场景 + 审核建议。"""
    filtered = _filter_items(items, category=category, decision=decision)
    total = len(filtered)
    page = filtered[offset:offset + limit]

    sections: dict[str, list[dict]] = {}
    for it in page:
        cat = it["category"] or "other"
        sections.setdefault(cat, []).append(it)
    order = sorted(
        sections.keys(),
        key=lambda c: (0 if c in CATEGORY_LABELS else 1, CATEGORY_LABELS.get(c, c)),
    )
    section_list = []
    for cat in order:
        its = sections[cat]
        section_list.append({
            "key": cat,
            "title": CATEGORY_LABELS.get(cat, cat),
            "description": f"{len(its)} 个项目",
            "items": its,
        })

    # headline: 今日最值得关注 (action + 当周新仓库, 按 star 排序)
    headline_items = sorted(
        [it for it in page if it["category_decision"] == "action" or it["is_new"]],
        key=lambda it: (it["stars"] or 0),
        reverse=True,
    )[:8]

    return {
        "meta": {
            "schema_version": "1.0",
            "mode": "human",
            "date": date,
            "generated_at": _now_iso(),
            "total": total,
            "limit": limit,
            "offset": offset,
            "sources": ["github-repos"],
        },
        "headline": {
            "title": "今日最值得关注",
            "items": headline_items,
        },
        "sections": section_list,
    }


def build_ai_feed(items: list[dict], date: str, limit: int = 100,
                  offset: int = 0, category: str | None = None,
                  decision: str | None = None) -> dict:
    """AI 优先信息流: 扁平条目 + content 正文 (机器可直接消费)。"""
    filtered = _filter_items(items, category=category, decision=decision)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    for it in page:
        # 显式生成 content 字段 (AI 消费正文)
        parts = [it["summary_zh"] or it["description"] or it["title"]]
        if it.get("use_case"):
            parts.append(f"适用场景: {it['use_case']}")
        if it.get("function_tags"):
            parts.append("功能标签: " + ", ".join(it["function_tags"]))
        it["content"] = "\n".join(parts)
    return {
        "meta": {
            "schema_version": "1.0",
            "mode": "ai",
            "date": date,
            "generated_at": _now_iso(),
            "total": total,
            "limit": limit,
            "offset": offset,
            "sources": ["github-repos"],
        },
        "items": page,
    }


def _filter_items(items: list[dict], category: str | None = None,
                  decision: str | None = None) -> list[dict]:
    out = items
    if category:
        out = [it for it in out if it.get("category") == category]
    if decision:
        out = [it for it in out if it.get("category_decision") == decision]
    return out


def get_feed(mode: str = "human", date: str | None = None, limit: int = 50,
             offset: int = 0, category: str | None = None,
             decision: str | None = None, store: ReserveStore | None = None,
             prefer_snapshot: bool = False) -> dict:
    """对外信息流主入口。

    数据来源优先级:
      1. 指定日期快照 (date 显式给出时, 从快照取当日数据)
      2. 储备库 (未指定日期时默认读 LanceDB 储备库, 数据最全)
      3. 降级: 最近一次快照
    """
    date = date or _today()

    if date and (date != _today() or prefer_snapshot):
        items = _load_snapshot_items(date)
    else:
        items = []
        try:
            store = store or ReserveStore()
            repos = store.all_repos(limit=5000)
            items = [_repo_to_item(r) for r in repos]
        except Exception:
            items = []
        if not items:
            items = _load_snapshot_items(date)

    # ISSUE #5: 追加多源适配器条目 (CNB 新项目 / 论文 / 热点 / 新闻 / 预测市场)
    items = items + _load_adapter_items()

    if mode == "ai":
        return build_ai_feed(items, date, limit=limit, offset=offset,
                             category=category, decision=decision)
    return build_human_feed(items, date, limit=limit, offset=offset,
                            category=category, decision=decision)


def get_items_timeline(date: str | None = None, category: str | None = None,
                       source: str | None = None, item_type: str | None = None,
                       tag: str | None = None, limit: int = 200,
                       offset: int = 0, sort: str = "date_desc",
                       store: ReserveStore | None = None) -> dict:
    """多源条目时间线 (ISSUE #5: 数据保存到 LanceDB, 按时间和功能排布)。

    LanceDB source_items 表按 date (采集日期) + category/tags/type/source (功能)
    排布查询, 供 Web「今日汇总」时间线页签与 REST API 使用。

    例:
      get_items_timeline()                              # 全部 (按日期倒序)
      get_items_timeline(date="2026-08-09")             # 某日
      get_items_timeline(category="papers")             # 论文
      get_items_timeline(date="2026-08-09", tag="mcp") # 某日某功能
    """
    store = store or ReserveStore()
    rows = store.items_query(date=date, category=category, source=source,
                             item_type=item_type, tag=tag, limit=limit,
                             offset=offset, sort=sort)
    items = [it for it in (_item_row_to_item(r) for r in rows) if it]
    dates = store.items_dates()
    return {
        "mode": "timeline",
        "generated_at": _now_iso(),
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "filters": {
            "date": date, "category": category, "source": source,
            "item_type": item_type, "tag": tag,
        },
        "available_dates": dates[:60],
        "items": items,
    }
