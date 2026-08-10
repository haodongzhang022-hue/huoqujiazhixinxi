"""传导网络分析 —— 把「两两关联边」升级为「网络」视角。

ISSUE #7 要求的是「各个小目录之间广泛的相互关联」。单条边 (A→B) 已经能回答
「A 对 B 的影响有多大、预测能力够不够」；但**跨市场/跨品种/跨国家**的网络结构
（谁影响全局、哪些品种抱团联动、风险沿什么路径传导）需要站在整张关联矩阵之上
才能回答。本模块基于 `evaluate_all` 产出的有向边构建加权有向图，提供:

  1. 节点中心性  —— 每个维度在网络中的影响地位 (出强度/入强度/总强度/中介中心性)
  2. 强关联簇    —— 关系紧密的品种群 (社团发现, 自底向上凝聚)
  3. 传导路径    —— 从源节点到目标节点的强传导链路 (DAG 最长/最强路径)
  4. 网络摘要    —— 节点数/边数/密度/最大簇/最强枢纽, 供页面与 API 直接消费

数据契约 (与 engine 输出兼容):
  input : [{edge, from, to, strength, sign, stability, lag, model, ...}, ...]
  output: {nodes, edges, clusters, paths, summary}
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from reserve.relations.dims import Dim, parse_dim, relationship_kind, layer_of_field


def _safe_key(d: dict) -> str:
    """把 from/to 维度字典转成规范化 key (与 dims.parse_dim().key 一致)。"""
    if isinstance(d, dict):
        return ".".join([str(d.get(k, "*")) for k in ("market", "country", "exchange",
                                                       "symbol", "asset", "timeframe")])
    return str(d)


def _dim_obj(d) -> Dim:
    """把维度字典/字符串/Dim 统一转成 Dim 对象。"""
    if isinstance(d, Dim):
        return d
    return parse_dim(d)


def _layer_group(dim: Dim) -> str:
    """节点所属的功能域分层分组：取维度里**最顶层(漏斗口)**已指定字段作为分组标签。

    用于漏斗分层展示——同一资产大类(功能域)的节点归到同一组/行，
    体现“漏斗：资产大类 → 地区 → 交易所 → 品种 → 交易类型 → 时间级别”。
    """
    act = dim.active_layers()
    if not act:
        return "*"
    # 取漏斗最顶层（最靠漏斗口、最深/最粗的功能域）作为归属
    top = act[0]
    return f"{top['label']}·{top['value']}"


def build_network(edges: list[dict], min_strength: float = 0.1) -> dict:
    """从有向边列表构建加权有向网络。"""
    nodes: dict[str, dict] = {}
    links: list[dict] = []
    adj: dict[str, list[tuple[str, float, dict]]] = defaultdict(list)

    for e in edges:
        strength = float(e.get("strength") or 0.0)
        if strength < min_strength:
            continue
        fk = _safe_key(e.get("from"))
        tk = _safe_key(e.get("to"))
        if fk == tk:
            continue
        f_dim = _dim_obj(e.get("from"))
        t_dim = _dim_obj(e.get("to"))
        rel = relationship_kind(f_dim, t_dim)
        for k, label, dim in ((fk, e.get("from"), f_dim), (tk, e.get("to"), t_dim)):
            if k not in nodes:
                nodes[k] = {
                    "key": k,
                    "dim": label,
                    "funnel": dim.funnel_label(),
                    "layer_group": _layer_group(dim),
                    "active_layers": dim.active_layers(),
                    "in_strength": 0.0,
                    "out_strength": 0.0,
                    "total_strength": 0.0,
                    "in_edges": 0,
                    "out_edges": 0,
                    "degree": 0,
                }
        nodes[fk]["out_strength"] += strength
        nodes[fk]["out_edges"] += 1
        nodes[tk]["in_strength"] += strength
        nodes[tk]["in_edges"] += 1
        nodes[fk]["total_strength"] += strength
        nodes[tk]["total_strength"] += strength
        nodes[fk]["degree"] += 1
        nodes[tk]["degree"] += 1
        adj[fk].append((tk, strength, e))
        links.append({
            "edge": e.get("edge"),
            "from": fk,
            "to": tk,
            "strength": round(strength, 4),
            "sign": e.get("sign", 0),
            "lag": e.get("lag", 0),
            "stability": round(float(e.get("stability") or 0.0), 4),
            "model": e.get("model", ""),
            "relation_kind": rel["kind"],
            "intra_layer": rel["kind"] == "intra_layer",
            "inter_layer": rel["kind"] == "inter_layer",
            "diff_fields": rel.get("diff_fields", []),
            "boundary_layer": rel.get("boundary_layer"),
            "verdict": (e.get("comparison") or {}).get("verdict")
            if isinstance(e.get("comparison"), dict) else None,
        })

    # 中心性 (归一化到 0~1, 便于跨网络比较)
    max_in = max((v["in_strength"] for v in nodes.values()), default=0.0)
    max_out = max((v["out_strength"] for v in nodes.values()), default=0.0)
    max_tot = max((v["total_strength"] for v in nodes.values()), default=0.0)
    for k, v in nodes.items():
        v["in_centrality"] = round(v["in_strength"] / max_in, 4) if max_in else 0.0
        v["out_centrality"] = round(v["out_strength"] / max_out, 4) if max_out else 0.0
        v["total_centrality"] = round(v["total_strength"] / max_tot, 4) if max_tot else 0.0
        v["hub_score"] = v["out_centrality"] * 0.6 + v["total_centrality"] * 0.4
        v["authority_score"] = v["in_centrality"] * 0.6 + v["total_centrality"] * 0.4

    # 强关联簇 (自底向上凝聚: 把双向且强度达阈值的节点归并)
    clusters = _cluster(nodes, links, adj, min_strength)
    # 层内/层间统计 (漏斗分层视角)
    intra = [l for l in links if l["intra_layer"]]
    inter = [l for l in links if l["inter_layer"]]
    # 按功能域层分组 (layer_group) 归集节点
    by_group: dict[str, list[dict]] = defaultdict(list)
    for n in nodes.values():
        by_group[n["layer_group"]].append(n)
    layer_groups = [
        {"label": g, "nodes": sorted(v, key=lambda x: -x["total_strength"]),
         "count": len(v)}
        for g, v in sorted(by_group.items(), key=lambda kv: -len(kv[1]))
    ]
    return {
        "nodes": sorted(nodes.values(), key=lambda v: -v["total_centrality"]),
        "edges": links,
        "clusters": clusters,
        "layer_groups": layer_groups,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(links),
            "intra_layer_edges": len(intra),
            "inter_layer_edges": len(inter),
            "density": round(len(links) / (len(nodes) * (len(nodes) - 1)), 4)
            if len(nodes) > 1 else 0.0,
            "cluster_count": len(clusters),
            "top_hubs": sorted(nodes.values(), key=lambda v: -v["hub_score"])[:5],
            "top_authorities": sorted(nodes.values(), key=lambda v: -v["authority_score"])[:5],
            "strongest_link": max(links, key=lambda l: l["strength"]) if links else None,
        },
    }


def _cluster(nodes: dict, links: list[dict], adj: dict, min_strength: float) -> list[dict]:
    """自底向上社团发现: 强双向互连的节点归入同一簇。

    以「双向边强度 ≥ min_strength×1.5」为强连接标准做并查集合并。
    """
    parent = {k: k for k in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    both = defaultdict(set)
    for l in links:
        both[l["from"]].add(l["to"])
    for l in links:
        if l["to"] in both.get(l["from"], set()) and l["from"] in both.get(l["to"], set()):
            if l["strength"] >= min_strength * 1.5:
                union(l["from"], l["to"])

    groups: dict[str, list[str]] = defaultdict(list)
    for k in nodes:
        groups[find(k)].append(k)
    clusters = []
    for root, members in groups.items():
        if len(members) == 1:
            continue  # 单点不成簇
        total = sum(nodes[m]["total_strength"] for m in members)
        clusters.append({
            "id": f"cluster-{len(clusters) + 1}",
            "members": members,
            "size": len(members),
            "total_strength": round(total, 4),
            "label": " + ".join(members),
        })
    clusters.sort(key=lambda c: -c["size"])
    return clusters


def strongest_paths(edges: list[dict], source: str | None = None,
                    target: str | None = None, max_depth: int = 5,
                    min_strength: float = 0.1, top: int = 5) -> list[dict]:
    """从源到目标的强传导路径 (基于有向图, 路径强度 = 边强度乘积)。

    - 不指定 source/target 时, 自动找「总强度最大的源 → 总入强度最大的目标」;
    - 用 BFS + 剪枝 (仅保留强度达阈值的边), 输出 Top 路径。
    """
    adj: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    nodes: set[str] = set()
    for e in edges:
        fk, tk = _safe_key(e.get("from")), _safe_key(e.get("to"))
        s = float(e.get("strength") or 0.0)
        if s < min_strength or fk == tk:
            continue
        adj[fk].append((tk, s, e.get("edge", "")))
        nodes.add(fk)
        nodes.add(tk)

    if source is None:
        out_sum = defaultdict(float)
        in_sum = defaultdict(float)
        for fk, tk, s, _ in [(f, t, s, e) for f in adj for t, s, e in adj[f]]:
            out_sum[fk] += s
            in_sum[tk] += s
        source = max(out_sum, key=out_sum.get) if out_sum else None
    if target is None:
        in_sum = defaultdict(float)
        for f in adj:
            for t, s, _ in adj[f]:
                in_sum[t] += s
        target = max(in_sum, key=in_sum.get) if in_sum else None
    if source is None or target is None or source not in adj:
        return []

    # BFS 枚举路径 (限制深度, 去环)
    results: list[dict] = []
    queue = deque([(source, [source], 1.0, [])])
    while queue:
        cur, path, strength, edge_list = queue.popleft()
        if len(path) > max_depth:
            continue
        if cur == target and len(path) >= 2:
            results.append({
                "path": list(path),
                "edges": list(edge_list),
                "strength": round(strength, 4),
                "length": len(path) - 1,
            })
            continue
        for nxt, s, edge in sorted(adj[cur], key=lambda x: -x[1]):
            if nxt in path:
                continue
            queue.append((nxt, path + [nxt], strength * s, edge_list + [edge]))
    results.sort(key=lambda p: -p["strength"])
    return results[:top]


def network_summary(edges: list[dict], min_strength: float = 0.1) -> dict:
    """网络摘要 (供页面顶部卡片/API 直接消费)。"""
    net = build_network(edges, min_strength=min_strength)
    s = net["summary"]
    return {
        "nodes": s["node_count"],
        "edges": s["edge_count"],
        "density": s["density"],
        "clusters": s["cluster_count"],
        "top_hubs": [{"key": n["key"], "hub_score": n["hub_score"],
                      "out_strength": round(n["out_strength"], 4)}
                     for n in s["top_hubs"]],
        "top_authorities": [{"key": n["key"], "authority_score": n["authority_score"],
                             "in_strength": round(n["in_strength"], 4)}
                            for n in s["top_authorities"]],
        "strongest_link": s["strongest_link"],
    }
