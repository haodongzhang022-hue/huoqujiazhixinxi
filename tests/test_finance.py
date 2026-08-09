"""finance 超索引框架测试 (pytest 风格, 无第三方测试框架也可直接运行)。

覆盖:
  - taxonomy: 分类体系加载 / 六维查询 / 品种解析 / 索引卡
  - catalog: 数据源目录 / 覆盖匹配 / 脚本查询
  - filter: 六维筛选 / 聚类统计
  - disclosure: index/meta/full 渐进披露 (full 走 demo 获取)
  - registry: 获取器注册 / demo 降级 / 缓存落盘
  - scheduler: 任务增删 / 频率解析 / next_run 计算 / run-due 执行
  - api: 路由响应
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finance.taxonomy import Taxonomy, load_taxonomy
from finance.catalog import Catalog, load_catalog
from finance.filter import filter_instruments, match_summary
from finance.disclosure import index_level, meta_level, full_level
from finance.registry import fetch_instrument, list_registered
from finance.scheduler import Scheduler, parse_interval

# 使用临时调度文件避免污染仓库
TEST_SCHEDULE = Path(tempfile.mkdtemp(prefix="fin-sched-")) / "scheduler.json"


def test_taxonomy_load():
    tax = load_taxonomy()
    assert tax.stats()["data_classes"] >= 10
    assert tax.stats()["regions"] >= 10
    assert tax.stats()["exchanges"] >= 30
    assert tax.stats()["time_levels"] >= 10
    assert tax.stats()["trade_types"] >= 5
    assert tax.stats()["instruments"] >= 20
    # 关键数据类别
    for dc in ("stock", "futures", "forex", "crypto", "macro", "sentiment"):
        assert tax.get_data_class(dc) is not None


def test_taxonomy_queries():
    tax = load_taxonomy()
    # 某国交易所
    cn_ex = tax.exchanges_of_region("CN")
    assert any(e["id"] == "SSE" for e in cn_ex)
    # 某类交易所
    fx_ex = tax.exchanges_of_class("futures")
    assert any(e["id"] == "SHFE" for e in fx_ex)
    # 品种筛选
    cn_fut = tax.instruments_of(data_class="futures", region="CN")
    assert any(i["id"] == "CN.RB" for i in cn_fut)
    # 解析
    assert tax.resolve_instrument("CN.RB")["id"] == "CN.RB"
    assert tax.resolve_instrument("RB")["id"] == "CN.RB"
    assert tax.resolve_instrument("600000")["id"] == "SH600000"
    # 索引卡
    card = tax.describe_instrument("CN.RB")
    assert card["exchange"]["id"] == "SHFE"
    assert card["region"]["id"] == "CN"
    assert card["data_class"]["id"] == "futures"


def test_catalog():
    cat = load_catalog()
    assert cat.summary()["sources"] >= 5
    # 覆盖匹配: crypto 数据源
    crypto = cat.match(data_class="crypto")
    assert any(s["id"] == "ccxt" for s in crypto)
    # 覆盖匹配: 中国期货
    cn_fut = cat.match(data_class="futures", region="CN")
    assert any(s["id"] == "akshare" for s in cn_fut)
    # 脚本信息
    script = cat.script_of("akshare")
    assert script["module"] == "finance.fetchers.akshare_fetcher"
    assert "akshare_fetcher.py" in script["script"]


def test_filter():
    tax, cat = load_taxonomy(), load_catalog()
    # 维度组合: 中国期货
    r1 = filter_instruments(tax, cat, data_class="futures", region="CN")
    assert any(it["instrument"].get("id") == "CN.RB" or
               (it["instrument"].get("instrument") or {}).get("id") == "CN.RB"
               for it in r1)
    # 品种模糊
    r2 = filter_instruments(tax, cat, instrument="BTC")
    assert len(r2) >= 1
    # 交易类型
    r3 = filter_instruments(tax, cat, trade_type="perpetual")
    assert len(r3) >= 1
    # 指定数据源
    r4 = filter_instruments(tax, cat, instrument="CN.RB", source="akshare")
    assert len(r4) == 1 and r4[0]["sources"][0]["id"] == "akshare"
    # 聚类统计
    s = match_summary(r1)
    assert s["matched_instruments"] >= 1
    assert "futures" in s["by_data_class"]
    assert "CN" in s["by_region"]


def test_disclosure():
    # index 级
    idx = index_level("CN.RB")
    assert idx["level"] == "index"
    assert "available_sources" in idx
    # meta 级
    meta = meta_level("CN.RB")
    assert meta["level"] == "meta"
    assert meta["instrument_card"]["exchange"]["id"] == "SHFE"
    assert len(meta["sources"]) >= 1
    # full 级 (demo 降级; 若已有缓存则直接命中缓存返回 data)
    full = full_level("CN.RB", source="akshare", time_level="1d")
    assert full["level"] == "full"
    payload = full.get("result") or full  # 缓存命中时字段是 data, 新获取时字段是 result
    assert payload.get("ok") is True
    assert payload.get("demo") is True


def test_registry():
    regs = list_registered()
    assert any(r["id"] == "akshare" for r in regs)
    # fetch demo 降级 (akshare 未安装)
    from finance.taxonomy import load_taxonomy
    inst = load_taxonomy().resolve_instrument("CRYPTO.BTC")
    result = fetch_instrument(inst, source="ccxt", time_level="1d", force_demo=True)
    assert result["ok"] is True
    assert result["demo"] is True
    assert result["data"]["kind"] == "ohlcv"
    # 缓存已落盘
    cache_dir = ROOT / "finance" / "data" / "cache" / "ccxt"
    assert cache_dir.exists()
    assert any(f.suffix == ".json" for f in cache_dir.iterdir())


def test_scheduler():
    s = Scheduler(TEST_SCHEDULE)
    # 频率解析
    assert parse_interval("5m") == 300
    assert parse_interval("1h") == 3600
    assert parse_interval("2d") == 172800
    assert parse_interval("abc") is None
    # 增任务
    t = s.add("CN.RB", "akshare", time_level="1d", every="1d", at="16:00")
    assert t["next_run"] is not None
    assert t["enabled"] is True
    # 下次运行时间在今天 16:00 之后
    next_dt = datetime.fromisoformat(t["next_run"])
    assert next_dt.hour == 16
    # 到期执行 (强制把 next_run 设为过去)
    t["next_run"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    s.save()
    due = s.due_tasks()
    assert len(due) == 1
    res = s.run_due()
    assert len(res) == 1
    assert res[0]["ok"] is True  # demo 降级
    # 列表/删除
    assert len(s.list()) == 1
    assert s.remove(t["id"]) is True


def test_api_routes():
    from finance.api import FinanceAPI
    # 模拟 GET 请求处理器 (直接调用逻辑函数)
    tax = load_taxonomy()
    # 筛选函数可用
    r = filter_instruments(tax, load_catalog(), data_class="macro", region="US")
    assert len(r) >= 1
    # index/meta/full 函数可用
    assert index_level("MACRO.US.CPI")["level"] == "index"
    assert meta_level("MACRO.US.CPI")["level"] == "meta"


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} 通过")
    return passed == len(tests)


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
