"""渠道分类漏斗 (reserve/channels) 测试 —— 分类→渠道→子渠道/单渠道叶节点 + 2级汇总。

覆盖:
  - CHANNEL_LAYERS: 分层定义 / 深度
  - parse_channel: 字符串/字典解析 + 分类推断
  - channel_of_item: 从 item 解析渠道路径
  - channel_tree: 渠道树 (2 级汇总 + 单渠道叶节点)
  - aggregate: 按层级汇总
  - match_channel / filter_items: 匹配到单渠道叶节点 + 取数据
  - add_channel_field: 格式统一 (补 channel / channel_path 字段)
  - fastapi: 路由注册
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reserve.channels import (Channel, channel_layers, parse_channel, channel_of_item,
                              channel_tree, aggregate, match_channel, filter_items,
                              add_channel_field, channel_depth, layer_of_field)

PASS = 0
FAIL = 0


def ok(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def sample_items():
    """构造一批跨分类/跨渠道/跨子渠道的归一化 item。"""
    return [
        {"category": "repos", "source": "cnb", "item_id": "r1",
         "title": "cnb repo 1", "extra": {"subchannel": "ai-agent"}},
        {"category": "repos", "source": "cnb", "item_id": "r2",
         "title": "cnb repo 2", "extra": {"subchannel": "ai-agent"}},
        {"category": "repos", "source": "github", "item_id": "r3",
         "title": "gh repo 3", "extra": {"subchannel": "rag-kb"}},
        {"category": "papers", "source": "arxiv", "item_id": "p1",
         "title": "paper 1", "extra": {"subchannel": "cs.AI"}},
        {"category": "papers", "source": "arxiv", "item_id": "p2",
         "title": "paper 2", "extra": {"subchannel": "cs.LG"}},
        {"category": "news", "source": "hackernews", "item_id": "n1",
         "title": "news 1", "extra": {}},
        {"category": "prediction", "source": "polymarket", "item_id": "pm1",
         "title": "pm 1", "extra": {}},
    ]


# ---- 1. CHANNEL_LAYERS 分层定义 ----
def test_layers():
    layers = channel_layers()
    ok("分层有3层", len(layers) == 3)
    ok("L0 是分类", layers[0]["id"] == "category" and layers[0]["order"] == 0)
    ok("L1 是渠道", layers[1]["id"] == "source" and layers[1]["order"] == 1)
    ok("L2 是子渠道", layers[2]["id"] == "subchannel" and layers[2]["order"] == 2)
    ok("channel_depth(source)=1", channel_depth("source") == 1)
    ok("layer_of_field(category).name", layer_of_field("category")["name"] == "分类/大类")


# ---- 2. parse_channel 解析 + 分类推断 ----
def test_parse_channel():
    ch = parse_channel("papers.arxiv")
    ok("两段解析: category", ch.category == "papers")
    ok("两段解析: source", ch.source == "arxiv")
    ok("两段解析: subchannel 缺省", ch.subchannel == "*")

    ch = parse_channel("papers.arxiv.cs.AI")
    ok("多段解析: subchannel 合并", ch.subchannel == "cs.AI")

    ch = parse_channel({"category": "news", "source": "rss"})
    ok("字典解析", ch.category == "news" and ch.source == "rss")

    # 分类推断: 只给 source -> 推断 category
    ch = match_channel("arxiv")
    ok("match 推断分类", ch.category == "papers" and ch.source == "arxiv")
    ch = match_channel("polymarket")
    ok("match 推断 prediction", ch.category == "prediction")


# ---- 3. channel_of_item 从 item 解析渠道路径 ----
def test_channel_of_item():
    items = sample_items()
    ch = channel_of_item(items[0])
    ok("item0 -> repos.cnb.ai-agent", ch.category == "repos" and ch.source == "cnb" and ch.subchannel == "ai-agent")
    ch = channel_of_item(items[3])
    ok("item3 -> papers.arxiv.cs.AI", ch.subchannel == "cs.AI")
    ch = channel_of_item(items[5])
    ok("无子渠道 -> *", ch.subchannel == "*")


# ---- 4. channel_tree 渠道树 ----
def test_channel_tree():
    items = sample_items()
    tree = channel_tree(items)
    ok("total_items = 7", tree["total_items"] == 7)
    t = tree["tree"]
    ok("有 repos 分类", "repos" in t)
    ok("repos 下含 cnb/github", "cnb" in t["repos"] and "github" in t["repos"])
    ok("repos 汇总 count=3", t["repos"]["_meta"]["count"] == 3)
    ok("cnb 渠道 count=2", t["repos"]["cnb"]["_meta"]["count"] == 2)
    ok("cnb/ai-agent 叶节点 count=2", t["repos"]["cnb"]["ai-agent"]["_meta"]["count"] == 2)
    ok("有 papers/arxiv/cs.AI 叶节点", t["papers"]["arxiv"]["cs.AI"]["_meta"]["count"] == 1)


# ---- 5. aggregate 2级汇总 ----
def test_aggregate():
    items = sample_items()
    # level=0 分类汇总
    by_cat = aggregate(items, level=0)
    cat_counts = {g["key"]: g["count"] for g in by_cat}
    ok("分类汇总 repos=3", cat_counts.get("repos") == 3)
    ok("分类汇总 papers=2", cat_counts.get("papers") == 2)
    # level=1 渠道汇总
    by_src = aggregate(items, level=1)
    src_counts = {g["key"]: g["count"] for g in by_src}
    ok("渠道汇总 arxiv=2", src_counts.get("arxiv") == 2)
    ok("渠道汇总 cnb=2", src_counts.get("cnb") == 2)
    # level=2 子渠道汇总
    by_sub = aggregate(items, level=2)
    sub_counts = {g["key"]: g["count"] for g in by_sub}
    ok("子渠道汇总 ai-agent=2", sub_counts.get("ai-agent") == 2)


# ---- 6. match_channel / filter_items ----
def test_filter_items():
    items = sample_items()
    # 分类汇总
    repos = filter_items(items, "repos")
    ok("取全部 repos=3", len(repos) == 3)
    # 渠道汇总
    arxiv = filter_items(items, "papers.arxiv")
    ok("取 arxiv=2", len(arxiv) == 2)
    # 单渠道叶节点
    leaf = filter_items(items, "papers.arxiv.cs.AI")
    ok("取 cs.AI 叶节点=1", len(leaf) == 1 and leaf[0]["title"] == "paper 1")
    # 无匹配
    none = filter_items(items, "papers.arxiv.cs.CL")
    ok("无匹配返回空", len(none) == 0)
    # 单渠道附带 channel 字段
    ok("过滤后带 channel_path", leaf[0].get("channel_path") == "papers.arxiv.cs.AI")


# ---- 7. add_channel_field 格式统一 ----
def test_add_channel_field():
    items = sample_items()
    rows = add_channel_field(items)
    ok("每条都补 channel", all("channel" in r and "channel_path" in r for r in rows))
    ok("channel 是 dict", isinstance(rows[0]["channel"], dict))
    ok("channel_path 格式统一", rows[3]["channel_path"] == "papers.arxiv.cs.AI")


# ---- 8. fastapi 路由注册 ----
def test_fastapi_routes():
    try:
        from reserve.fastapi_app import app
        routes = [r.path for r in app.routes]
        ok("注册 /api/v1/channels", any("/api/v1/channels" == p for p in routes))
        ok("注册 /api/v1/channels/aggregate", any("/api/v1/channels/aggregate" == p for p in routes))
        ok("注册 /api/v1/channels/items", any("/api/v1/channels/items" == p for p in routes))
        ok("注册 /api/v1/channels/match", any("/api/v1/channels/match" == p for p in routes))
    except ImportError:
        # 运行环境未安装 fastapi 时跳过 (路由注册逻辑在装有 fastapi 的服务环境执行)
        print("  ⚠️ 跳过 fastapi 路由测试 (环境未安装 fastapi)")
    except Exception as e:
        ok(f"fastapi 导入/路由检查 (异常: {e})", False)


def main():
    test_layers()
    test_parse_channel()
    test_channel_of_item()
    test_channel_tree()
    test_aggregate()
    test_filter_items()
    test_add_channel_field()
    test_fastapi_routes()
    print(f"\n渠道分类漏斗测试: {PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
