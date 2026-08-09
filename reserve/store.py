"""LanceDB 储备库存储层 (store.py)。

实现调研报告 §5.2 LanceDB 表结构 + 本地 repo_reserve 表设计：
  - repo_reserve 表 : 仓库主表 (统一 schema + 功能索引 + 三分类 + embedding)
  - repo_snapshots 表: 每日快照 (趋势回溯)
  - needs 表         : 条件触发引擎的未满足需求 (pending_needs)
  - source_items 表  : 多源每日信息 (ISSUE #5: CNB 新项目/论文/热点/科技进展/预测市场,
                      数据保存到 LanceDB, 按时间和功能排布, 支持按 date+category/tags 查询)

存储选择 (生产可切换):
  - LANCE_DIR 环境变量 -> LanceDB 目录 (默认 ./reserve_data)
  - LANCEDB_URI 环境变量 -> LanceDB 远程/对象存储 URI
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import lancedb
import pyarrow as pa

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "reserve_data"


def embed_dim() -> int:
    """储备库向量维度 (与 embedding 管道一致)。

    优先级: 环境变量 RESERVE_EMBED_DIM > EMBEDDING_MODEL/API 推断 > 默认 384。
    API embedding (如 text-embedding-3-small=1536) / Ollama (nomic-embed-text=768)
    维度与本地 TF hash 嵌入 (384) 不同, 建表时必须用实际维度。
    """
    env = os.environ.get("RESERVE_EMBED_DIM", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    # Ollama embedding 模型维度表
    ollama_dims = {
        "nomic-embed-text": 768,
        "bge-m3": 1024,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "snowflake-arctic-embed": 1024,
    }
    model = os.environ.get("EMBEDDING_MODEL", "").strip().lower()
    if model in ollama_dims:
        return ollama_dims[model]
    if model.startswith("text-embedding-3"):
        return 1536
    if model.startswith("text-embedding-ada"):
        return 1536
    return 384


# 仓库主表 schema (对齐调研报告 §5.2)
REPO_SCHEMA = {
    "repo_id": "str",              # 唯一键 = full_name
    "full_name": "str",
    "name": "str",
    "owner": "str",
    "url": "str",
    "homepage": "str",
    "description": "str",
    "description_zh": "str",       # 中文描述 (LLM/启发式)
    "language": "str",
    "topics": "list[str]",
    "stars": "int",
    "forks": "int",
    "stars_delta_24h": "int",
    "stars_delta_7d": "int",
    "forks_delta_7d": "int",
    "delta_window_days": "int",
    "is_new_this_week": "bool",
    "created_at": "str",
    "pushed_at": "str",
    "first_seen_at": "str",
    "source": "list[str]",
    "category": "str",
    "categories": "list[str]",
    "action_candidate": "bool",
    "delta_source": "str",
    # 功能索引 (核心差异化)
    "function_tags": "list[str]",
    "function_summary": "str",
    "use_case": "str",
    "ecosystem_fit": "str",
    # 条件判断结果
    "category_decision": "str",    # action / reserve / partial / ignore
    "decision_score": "float",
    "decision_reason": "str",
    # 触发引擎字段
    "matched_needs": "list[str]",
    "matched_scores": "list[float]",
    "matched_need_ids": "list[str]",
    "needs_rematch_ts": "str",
    "is_secondary": "bool",
    # LLM 增强字段
    "index_source": "str",     # heuristic / llm
    "indexed_at": "str",
    "review": "str",           # LLM 审核结果 (JSON 字符串)
    "review_status": "str",    # pending / approved / rejected / none
    "reviewed_at": "str",
    "updated_at": "str",
    "embedding": f"vector[{embed_dim()}]",
}

# 全文检索的文本拼接列 (FTS 索引建在这一列)
FTS_TEXT_COLUMN = "search_text"

# ============================================================
# 多源每日信息 items 表 (ISSUE #5: 数据保存到 LanceDB, 按时间和功能排布)
# ============================================================
# 统一存储 CNB 新项目 / 论文 / 热点 / 科技进展 / 预测市场 / GitHub 快照 等
# 所有数据源的归一化条目, 支持按日期 (date) 与功能 (category/tags/type) 排布查询。
ITEMS_SCHEMA = {
    "item_id": "str",           # 来源内唯一 id
    "source": "str",            # 数据源 id (cnb/github/arxiv/hackernews/polymarket/rss)
    "item_type": "str",         # 条目类型 repo/paper/trend/news/cnb-project/prediction
    "category": "str",          # 功能类别 (repos/papers/news/tech/prediction)
    "title": "str",
    "url": "str",
    "summary": "str",
    "tags": "list[str]",        # 功能标签
    "score": "float",           # 热度/重要性分数
    "published_at": "str",      # 发布时间 (ISO)
    "date": "str",              # 排布主键: 采集日期 YYYY-MM-DD (按时间排布)
    "first_seen_at": "str",     # 首次入库时间
    "updated_at": "str",        # 最后更新时间
    "extra": "str",             # 扩展字段 JSON 字符串
}
# items 表全文检索列
ITEMS_FTS_COLUMN = "search_text"


def table_name_items() -> str:
    """多源 items 表名 (环境变量可覆盖, 默认 source_items)。"""
    return os.environ.get("ITEMS_TABLE", "source_items")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_uri() -> str:
    uri = os.environ.get("LANCEDB_URI", "").strip() or os.environ.get("LANCE_DIR", "").strip()
    if uri:
        return uri
    return str(DEFAULT_DIR)


def table_name_repos() -> str:
    return os.environ.get("RESERVE_TABLE", "repo_reserve")


def table_name_snapshots() -> str:
    return os.environ.get("SNAPSHOT_TABLE", "repo_snapshots")


def _placeholder_default(key: str, typ: str):
    if typ.startswith("vector"):
        return [0.0] * int(typ.split("[")[1].rstrip("]"))
    if typ in ("list[str]", "list[float]"):
        return []
    if typ == "int":
        return 0
    if typ == "float":
        return 0.0
    if typ == "bool":
        return False
    return ""


class ReserveStore:
    """LanceDB 储备库封装。

    用法:
        store = ReserveStore()
        store.upsert_repos([...])          # 批量入库/更新 (增量合并)
        store.search_fts(text)             # 全文检索
        store.search_vector(emb)           # 向量检索
        store.search_hybrid(text, emb)     # 混合检索
        store.query(where, limit)          # SQL 过滤
        store.get_repo(full_name)
        store.delete_repo(full_name)
        store.snapshot_put(date, rows)     # 每日快照
        store.needs_put(needs) / needs_get()
        # ISSUE #5: 多源每日信息 (按时间/功能排布)
        store.upsert_items(items, date)    # 多源条目入库 (按采集日期)
        store.items_query(date, category, source, tag, limit)  # 按时间+功能查询
        store.items_count() / store.items_dates() / store.delete_items(date)
    """

    def __init__(self, uri: str | None = None):
        self.uri = uri or resolve_uri()
        if not self.uri.startswith(("s3://", "gs://", "az://", "http")):
            os.makedirs(self.uri, exist_ok=True)
        self.db = lancedb.connect(self.uri)
        self.repos_name = table_name_repos()
        self.snaps_name = table_name_snapshots()
        self.needs_name = "needs"
        self.items_name = table_name_items()

    # ---------- 表工具 ----------

    def list_tables(self) -> list[str]:
        try:
            return self.db.table_names()
        except Exception:
            return self.db.list_tables()

    def _open_repos(self):
        return self.db.open_table(self.repos_name)

    def _ensure_repos_table(self):
        """确保 repo_reserve 表存在 (不存在则用 pyarrow schema 建空表)。"""
        if self.repos_name in self.list_tables():
            return self._open_repos()
        schema = _repo_arrow_schema()
        self.db.create_table(self.repos_name, schema=schema)
        return self._open_repos()

    # ---------- repos 入库 (增量合并) ----------

    def upsert_repos(self, repos: list[dict]) -> dict:
        """批量入库: 已存在 -> 更新 (delete+add), 不存在 -> 插入; is_secondary 跳过。

        返回: {"inserted": n, "updated": m, "skipped_secondary": k, "total": t}
        """
        if not repos:
            return {"inserted": 0, "updated": 0, "skipped_secondary": 0, "total": 0}
        self._ensure_repos_table()
        existing_ids = set(self._all_repo_ids())
        to_insert, to_update = [], []
        skipped = 0
        for repo in repos:
            rid = repo.get("repo_id") or repo.get("full_name")
            if not rid:
                continue
            if repo.get("is_secondary"):
                skipped += 1
                continue
            row = normalize_repo_row(repo)
            if rid in existing_ids:
                to_update.append(row)
            else:
                to_insert.append(row)
        if to_insert:
            self._open_repos().add(to_insert)
        for row in to_update:
            # 向量列无法在 update 中直接写 -> delete + add
            self._open_repos().delete(f"repo_id = '{_esc(row['repo_id'])}'")
            self._open_repos().add([row])
        return {"inserted": len(to_insert), "updated": len(to_update),
                "skipped_secondary": skipped, "total": len(to_insert) + len(to_update)}

    def _all_repo_ids(self) -> set[str]:
        try:
            df = self._open_repos().to_pandas()
            return set(df["repo_id"].tolist())
        except Exception:
            return set()

    def get_repo(self, full_name: str) -> dict | None:
        try:
            res = self._open_repos().search().where(f"repo_id = '{_esc(full_name)}'", prefilter=True).limit(1).to_pandas()
            if len(res) == 0:
                return None
            return row_to_dict(res.iloc[0].to_dict())
        except Exception:
            return None

    def delete_repo(self, full_name: str) -> bool:
        try:
            self._open_repos().delete(f"repo_id = '{_esc(full_name)}'")
            return True
        except Exception:
            return False

    def query(self, where: str | None = None, limit: int = 100, columns: list[str] | None = None) -> list[dict]:
        try:
            tbl = self._open_repos()
            q = tbl.search()
            if where:
                q = q.where(where, prefilter=True)
            df = q.limit(limit).to_pandas()
            if columns:
                df = df[columns]
            return rows_to_dicts(df.to_dict("records"))
        except Exception as e:
            print(f"[store] query error: {e}")
            return []

    def count(self) -> int:
        try:
            return self._open_repos().count_rows()
        except Exception:
            return 0

    def all_repos(self, limit: int = 10000) -> list[dict]:
        try:
            return rows_to_dicts(self._open_repos().to_pandas().head(limit).to_dict("records"))
        except Exception:
            return []

    # ---------- 检索 ----------

    def _ensure_fts_index(self):
        try:
            tbl = self._open_repos()
            if not tbl.list_indices():
                tbl.create_fts_index(FTS_TEXT_COLUMN)
        except Exception as e:
            print(f"[store] fts index error: {e}")

    def search_fts(self, text: str, limit: int = 10, where: str | None = None) -> list[dict]:
        self._ensure_fts_index()
        try:
            tbl = self._open_repos()
            q = tbl.search(text, query_type="fts")
            if where:
                q = q.where(where, prefilter=True)
            return rows_to_dicts(q.limit(limit).to_pandas().to_dict("records"))
        except Exception as e:
            print(f"[store] fts error: {e}")
            return []

    def search_vector(self, embedding: list[float], limit: int = 10, where: str | None = None) -> list[dict]:
        try:
            tbl = self._open_repos()
            q = tbl.search(embedding)
            if where:
                q = q.where(where, prefilter=True)
            return rows_to_dicts(q.limit(limit).to_pandas().to_dict("records"))
        except Exception as e:
            print(f"[store] vector error: {e}")
            return []

    def search_hybrid(self, text: str, embedding: list[float], limit: int = 10,
                      fts_weight: float = 0.4, vec_weight: float = 0.6,
                      where: str | None = None) -> list[dict]:
        """混合检索: FTS + 向量 加权融合。"""
        fts_res = self.search_fts(text, limit=max(limit * 3, 30), where=where)
        vec_res = self.search_vector(embedding, limit=max(limit * 3, 30), where=where)
        scores: dict[str, dict] = {}
        for r in fts_res:
            rid = r.get("repo_id")
            scores.setdefault(rid, {"row": r, "score": 0.0})
            scores[rid]["score"] += fts_weight * (1.0 / (1.0 + float(r.get("_score", 1.0) or 1.0)))
        for r in vec_res:
            rid = r.get("repo_id")
            scores.setdefault(rid, {"row": r, "score": 0.0})
            scores[rid]["score"] += vec_weight * (1.0 / (1.0 + float(r.get("_distance", 1.0) or 1.0)))
        ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:limit]
        return [x["row"] for x in ranked]

    # ---------- 快照 ----------

    def snapshot_put(self, date: str, rows: list[dict], meta: dict | None = None) -> None:
        data = [{
            "date": date,
            "repo_id": r.get("repo_id") or r.get("full_name"),
            "full_name": r.get("full_name"),
            "stars": int(r.get("stars") or 0),
            "rank": int(r.get("rank") or 0),
            "is_new": bool(r.get("is_new_this_week")),
            "category": r.get("category"),
            "category_decision": r.get("category_decision"),
            "meta": json.dumps(meta or {}, ensure_ascii=False),
        } for r in rows]
        try:
            tbl = self.db.open_table(self.snaps_name)
            tbl.add(data)
        except Exception:
            self.db.create_table(self.snaps_name, data=data, mode="overwrite")

    def snapshot_query(self, date: str | None = None) -> list[dict]:
        try:
            tbl = self.db.open_table(self.snaps_name)
            if date:
                return tbl.search().where(f"date = '{date}'", prefilter=True).limit(10000).to_pandas().to_dict("records")
            return tbl.to_pandas().to_dict("records")
        except Exception:
            return []

    # ---------- needs (条件触发引擎) ----------

    def needs_put(self, needs: list[dict]) -> None:
        data = [{
            "id": n.get("id"),
            "text": n.get("text"),
            "keywords": n.get("keywords") or [],
            "status": n.get("status", "open"),
            "decision": n.get("decision", "LOG"),
            "matched_repos": json.dumps(n.get("matched_repos") or [], ensure_ascii=False),
            "created_at": n.get("created_at") or now_iso(),
            "updated_at": now_iso(),
        } for n in needs]
        try:
            tbl = self.db.open_table(self.needs_name)
            tbl.delete("id IS NOT NULL")
            if data:
                tbl.add(data)
        except Exception:
            if data:
                self.db.create_table(self.needs_name, data=data, mode="overwrite")

    def needs_get(self) -> list[dict]:
        try:
            tbl = self.db.open_table(self.needs_name)
            df = tbl.to_pandas()
            out = []
            for _, r in df.iterrows():
                row = row_to_dict(r.to_dict())
                row["matched_repos"] = json.loads(row.get("matched_repos") or "[]")
                out.append(row)
            return out
        except Exception:
            return []

    # ---------- 多源每日信息 items (ISSUE #5: 数据保存到 LanceDB, 按时间/功能排布) ----------

    def _ensure_items_table(self):
        """确保 source_items 表存在 (不存在则用 pyarrow schema 建空表)。"""
        if self.items_name in self.list_tables():
            return self.db.open_table(self.items_name)
        schema = _items_arrow_schema()
        self.db.create_table(self.items_name, schema=schema)
        return self.db.open_table(self.items_name)

    def _open_items(self):
        return self.db.open_table(self.items_name)

    def upsert_items(self, items: list[dict], date: str | None = None) -> dict:
        """多源条目入库 (LanceDB source_items 表, 按采集日期排布)。

        - date: 采集日期 YYYY-MM-DD, 缺省取当前 UTC 日期;
        - 已存在 (source + item_id + date 相同) 的记录先删后插 (增量更新);
        - 返回 {"inserted": n, "updated": m, "total": t}。
        """
        if not items:
            return {"inserted": 0, "updated": 0, "total": 0}
        d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._ensure_items_table()
        existing = self._all_item_ids(d)
        to_insert, to_update = [], []
        for it in items:
            row = normalize_item_row(it, date=d)
            key = (row["source"], row["item_id"])
            if key in existing:
                to_update.append(row)
            else:
                to_insert.append(row)
        if to_insert:
            try:
                self._open_items().add(to_insert)
            except Exception as e:
                print(f"[store] items add error: {e}")
        for row in to_update:
            try:
                self._open_items().delete(
                    f"source = '{_esc(row['source'])}' AND item_id = '{_esc(row['item_id'])}'"
                    f" AND date = '{_esc(row['date'])}'"
                )
                self._open_items().add([row])
            except Exception as e:
                print(f"[store] items update error: {e}")
        return {"inserted": len(to_insert), "updated": len(to_update),
                "total": len(to_insert) + len(to_update)}

    def _all_item_ids(self, date: str) -> set[tuple[str, str]]:
        try:
            df = self._open_items().search().where(
                f"date = '{_esc(date)}'", prefilter=True
            ).limit(100000).to_pandas()
            return set(zip(df["source"].tolist(), df["item_id"].tolist()))
        except Exception:
            return set()

    def items_query(self, date: str | None = None, category: str | None = None,
                    source: str | None = None, item_type: str | None = None,
                    tag: str | None = None, limit: int = 200,
                    offset: int = 0, sort: str = "date_desc") -> list[dict]:
        """多源条目查询: 按时间 (date) + 功能 (category/tags/type/source) 排布。

        例:
          items_query(date="2026-08-09")                     # 某日全部
          items_query(category="papers")                     # 全部论文
          items_query(date="2026-08-09", tag="mcp")         # 某日带 mcp 标签
          items_query(source="cnb")                          # 某源全部
        """
        try:
            tbl = self._open_items()
            conds = []
            if date:
                conds.append(f"date = '{_esc(date)}'")
            if category:
                conds.append(f"category = '{_esc(category)}'")
            if source:
                conds.append(f"source = '{_esc(source)}'")
            if item_type:
                conds.append(f"item_type = '{_esc(item_type)}'")
            if tag:
                conds.append(f"array_has(tags, '{_esc(tag)}')")
            where = " AND ".join(conds) if conds else None
            q = tbl.search()
            if where:
                q = q.where(where, prefilter=True)
            df = q.limit(limit + offset).to_pandas()
            if offset:
                df = df.iloc[offset:]
            if sort == "date_desc":
                df = df.sort_values("date", ascending=False)
            elif sort == "score_desc":
                df = df.sort_values("score", ascending=False)
            elif sort == "published_desc":
                df = df.sort_values("published_at", ascending=False)
            rows = rows_to_dicts(df.to_dict("records"))
            for r in rows:
                try:
                    r["extra"] = json.loads(r.get("extra") or "{}")
                except Exception:
                    r["extra"] = {}
            return rows
        except Exception as e:
            print(f"[store] items_query error: {e}")
            return []

    def items_count(self) -> int:
        try:
            return self._open_items().count_rows()
        except Exception:
            return 0

    def items_dates(self) -> list[str]:
        """已入库的日期列表 (按时间排布用, 倒序)。"""
        try:
            df = self._open_items().to_pandas()
            return sorted(df["date"].dropna().unique().tolist(), reverse=True)
        except Exception:
            return []

    def delete_items(self, date: str | None = None, source: str | None = None) -> int:
        """删除某日/某源的多源条目 (date 必填, source 可选)。"""
        conds = []
        if date:
            conds.append(f"date = '{_esc(date)}'")
        if source:
            conds.append(f"source = '{_esc(source)}'")
        if not conds:
            return 0
        try:
            self._open_items().delete(" AND ".join(conds))
            return 1
        except Exception as e:
            print(f"[store] delete_items error: {e}")
            return 0


def normalize_item_row(it: dict, date: str | None = None) -> dict:
    """多源适配器 item -> ITEMS_SCHEMA 行 (补默认值 + search_text 拼接列)。"""
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    published = it.get("published_at") or it.get("published") or ""
    tags = it.get("tags") or it.get("function_tags") or []
    extra = it.get("extra") or {}
    row = {
        "item_id": str(it.get("item_id") or it.get("id") or ""),
        "source": str(it.get("source") or "unknown"),
        "item_type": str(it.get("item_type") or it.get("type") or ""),
        "category": str(it.get("category") or "other"),
        "title": str(it.get("title") or ""),
        "url": str(it.get("url") or ""),
        "summary": str(it.get("summary") or it.get("description") or ""),
        "tags": [str(t) for t in tags],
        "score": float(it.get("score") or 0),
        "published_at": published,
        "date": d,
        "first_seen_at": it.get("first_seen_at") or now_iso(),
        "updated_at": now_iso(),
        "extra": json.dumps(extra, ensure_ascii=False),
    }
    row[ITEMS_FTS_COLUMN] = " ".join(filter(None, [
        row["title"], row["summary"], row["source"], row["category"],
        " ".join(row["tags"]),
    ])).lower()
    return row


def _items_arrow_schema():
    """source_items 表的 pyarrow schema (建空表用)。"""
    fields = []
    for key, typ in ITEMS_SCHEMA.items():
        if typ == "list[str]":
            fields.append(pa.field(key, pa.list_(pa.string())))
        elif typ == "float":
            fields.append(pa.field(key, pa.float64()))
        elif typ == "int":
            fields.append(pa.field(key, pa.int64()))
        else:
            fields.append(pa.field(key, pa.string()))
    fields.append(pa.field(ITEMS_FTS_COLUMN, pa.string()))
    return pa.schema(fields)


def normalize_repo_row(repo: dict) -> dict:
    """把任意来源的仓库 dict 归一化为 REPO_SCHEMA 行 (缺失字段补默认值)。

    同时拼接 search_text 列供全文检索。
    """
    row = {}
    for key, typ in REPO_SCHEMA.items():
        val = repo.get(key)
        if key == "repo_id" and not val:
            val = repo.get("full_name")
        if key == "review" and isinstance(val, dict):
            val = json.dumps(val, ensure_ascii=False)  # dict -> JSON 字符串持久化
        if val is None:
            row[key] = _placeholder_default(key, typ)
        elif typ.startswith("vector"):
            row[key] = [float(x) for x in val]
        elif typ == "list[str]":
            row[key] = [str(x) for x in val] if isinstance(val, list) else ([str(val)] if val != "" else [])
        elif typ == "list[float]":
            row[key] = [float(x) for x in val] if isinstance(val, list) else ([float(val)] if val != "" else [])
        elif typ == "int":
            try:
                row[key] = int(val)
            except (TypeError, ValueError):
                row[key] = 0
        elif typ == "float":
            try:
                row[key] = float(val)
            except (TypeError, ValueError):
                row[key] = 0.0
        elif typ == "bool":
            row[key] = bool(val)
        else:
            row[key] = str(val) if val is not None else ""
    # 全文检索拼接列
    row[FTS_TEXT_COLUMN] = " ".join(filter(None, [
        row.get("name", ""),
        row.get("full_name", ""),
        row.get("description", ""),
        row.get("description_zh", ""),
        row.get("function_summary", ""),
        row.get("use_case", ""),
        " ".join(row.get("topics", []) or []),
        " ".join(row.get("function_tags", []) or []),
    ])).lower()
    row["updated_at"] = now_iso()
    return row


def row_to_dict(row: dict) -> dict:
    """LanceDB 读回的行 -> 对外 dict（review JSON 字符串反序列化, numpy 标量/数组转原生类型）。

    LanceDB to_pandas 取回时 list 列是 numpy.ndarray、数值列是 numpy 标量,
    下游 `if not function_tags` / json.dumps 会报错, 统一在这里清洗。
    """
    import numpy as np
    out = {}
    for k, v in row.items():
        if k == "review" and isinstance(v, str) and v:
            try:
                out[k] = json.loads(v)
            except Exception:
                out[k] = v
        elif isinstance(v, np.ndarray):
            out[k] = v.tolist()
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = float(v)
        elif isinstance(v, (np.bool_,)):
            out[k] = bool(v)
        elif isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out


def rows_to_dicts(rows: list[dict]) -> list[dict]:
    return [row_to_dict(r) for r in rows]


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _repo_arrow_schema():
    """仓库主表的 pyarrow schema (用于建空表, 避免 List(Null) 类型推断问题)。"""
    fields = []
    for key, typ in REPO_SCHEMA.items():
        if typ.startswith("vector"):
            dim = int(typ.split("[")[1].rstrip("]"))
            fields.append(pa.field(key, pa.list_(pa.float32(), dim)))
        elif typ == "list[str]":
            fields.append(pa.field(key, pa.list_(pa.string())))
        elif typ == "list[float]":
            fields.append(pa.field(key, pa.list_(pa.float32())))
        elif typ == "int":
            fields.append(pa.field(key, pa.int64()))
        elif typ == "float":
            fields.append(pa.field(key, pa.float64()))
        elif typ == "bool":
            fields.append(pa.field(key, pa.bool_()))
        else:
            fields.append(pa.field(key, pa.string()))
    fields.append(pa.field(FTS_TEXT_COLUMN, pa.string()))
    return pa.schema(fields)
