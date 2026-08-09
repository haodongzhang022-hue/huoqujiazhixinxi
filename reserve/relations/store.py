"""关联矩阵持久化 —— JSON 文件存储 (兼容 LanceDB 表结构预留)。

存储结构 (relation_store/):
  relation_store/
    matrix.json          # 矩阵骨架 (维度 + 两两有序边清单)
    edges/<edge>.json    # 每条边的评估结果 (edge = "A -> B", 文件名做安全转义)
    comparisons/<edge>.json  # 每条边的 预测 vs 实际 对比
    meta.json            # 更新时间/模型默认/统计

env 覆盖: RELATION_DIR 环境变量可指定目录。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIR = Path(os.environ["RELATION_DIR"]) if os.environ.get("RELATION_DIR") \
    else Path(__file__).resolve().parent.parent.parent / "relation_store"


def _safe(name: str) -> str:
    """把 edge key "a.b.c -> d.e.f" 转成安全文件名。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RelationStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else DEFAULT_DIR
        self.edges_dir = self.root / "edges"
        self.comps_dir = self.root / "comparisons"
        self.edges_dir.mkdir(parents=True, exist_ok=True)
        self.comps_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 矩阵骨架 ----------
    def save_matrix(self, matrix: dict) -> Path:
        p = self.root / "matrix.json"
        matrix["updated_at"] = now_iso()
        p.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_matrix(self) -> dict | None:
        p = self.root / "matrix.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    # ---------- 边评估结果 ----------
    def save_edge(self, result: dict) -> Path:
        edge = result.get("edge") or result.get("direction") or "unknown"
        result["saved_at"] = now_iso()
        p = self.edges_dir / f"{_safe(edge)}.json"
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_edge(self, edge: str) -> dict | None:
        p = self.edges_dir / f"{_safe(edge)}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def list_edges(self) -> list[dict]:
        out = []
        for p in sorted(self.edges_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def count_edges(self) -> int:
        return len(list(self.edges_dir.glob("*.json")))

    # ---------- 预测 vs 实际 对比 ----------
    def save_comparison(self, edge: str, comparison: dict) -> Path:
        comparison["saved_at"] = now_iso()
        p = self.comps_dir / f"{_safe(edge)}.json"
        p.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_comparison(self, edge: str) -> dict | None:
        p = self.comps_dir / f"{_safe(edge)}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def list_comparisons(self) -> list[dict]:
        out = []
        for p in sorted(self.comps_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def save_meta(self, meta: dict) -> Path:
        meta["updated_at"] = now_iso()
        p = self.root / "meta.json"
        p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_meta(self) -> dict | None:
        p = self.root / "meta.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
