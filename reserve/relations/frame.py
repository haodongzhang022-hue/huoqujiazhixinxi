"""矩阵定义 —— 目标集展开为「全两两有序对」（排除自环）。

ISSUE #7 强调: 「这不是一种影响，是两两需要评估」——即 A→B 与 B→A 是两条独立的有向边。
本模块把目标维度集展开为完整的有向笛卡尔积，支持:
  - 自动去重 (同一目标只出现一次)
  - 排除自环 (A==A)
  - 允许相同维度的不同小目录 (例如同品种不同时间级别、同品种现货 vs 合约) 参与评估
"""

from __future__ import annotations

from reserve.relations.dims import Dim, parse_dim


def expand_targets(targets: list[str | dict | Dim]) -> list[Dim]:
    """把用户给定的目标集展开为规范化 Dim 列表（去重、保持顺序）。"""
    seen = set()
    out: list[Dim] = []
    for t in targets:
        d = t if isinstance(t, Dim) else parse_dim(t)
        if d.key in seen:
            continue
        seen.add(d.key)
        out.append(d)
    return out


def ordered_pairs(targets: list[str | dict | Dim], self_loops: bool = False) -> list[tuple[Dim, Dim]]:
    """生成全两两有序对 (A→B, 方向敏感)。

    self_loops=True 时保留 A==A（用于研究“自身动量/自相关”，默认排除）。
    """
    dims = expand_targets(targets)
    pairs: list[tuple[Dim, Dim]] = []
    for a in dims:
        for b in dims:
            if not self_loops and a == b:
                continue
            pairs.append((a, b))
    return pairs


def pair_key(a: Dim, b: Dim) -> str:
    """有向边唯一 key: a->b。"""
    return f"{a.key} -> {b.key}"


def reverse_pair_key(key: str) -> str:
    """有向边反向 key: "a -> b" -> "b -> a"。"""
    if " -> " in key:
        left, right = key.split(" -> ", 1)
        return f"{right} -> {left}"
    return key


def build_matrix(targets: list[str | dict | Dim], self_loops: bool = False) -> dict:
    """构建关联矩阵骨架（全部两两有序边，尚未计算值）。"""
    dims = expand_targets(targets)
    pairs = ordered_pairs(dims, self_loops=self_loops)
    return {
        "schema_version": "1.0",
        "self_loops": self_loops,
        "dimensions": [d.to_dict() for d in dims],
        "dimension_keys": [d.key for d in dims],
        "pair_count": len(pairs),
        "pairs": [
            {
                "from": a.to_dict(),
                "from_key": a.key,
                "to": b.to_dict(),
                "to_key": b.key,
                "edge": pair_key(a, b),
            }
            for a, b in pairs
        ],
    }
