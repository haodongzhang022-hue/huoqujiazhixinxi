"""tests/test_lance.py —— LanceDB 统一数据管理层测试。

覆盖:
  - 建表/种子初始化 (channels/column_defs/params)
  - 渠道获取 -> 数据落库 (data_records)
  - 任务调度 (fetch_tasks add/run-due/run-all)
  - 渠道挖掘 (discover/evaluate/promote)
  - 数据查询/统计
"""

import os
import sys
import tempfile
from pathlib import Path

# 临时 LanceDB 目录 (不污染仓库数据)
_TMP = Path(tempfile.mkdtemp(prefix="lance-test-"))
os.environ["FINANCE_LANCE_DIR"] = str(_TMP)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from finance.lance.store import LanceStore  # noqa: E402
from finance.lance.registry import ChannelRegistry  # noqa: E402
from finance.lance.tasks import TaskManager  # noqa: E402
from finance.lance.discovery import ChannelDiscovery  # noqa: E402
from finance.lance.datastore import DataStore  # noqa: E402
from finance.lance.logs import RunLogger  # noqa: E402


@pytest.fixture(scope="module")
def store():
    return LanceStore(_TMP)


@pytest.fixture(scope="module")
def reg(store):
    return ChannelRegistry(store)


def test_init_tables(store):
    """七张表全部创建。"""
    tables = set(store.list_tables())
    assert {"channels", "column_defs", "params", "fetch_tasks",
            "run_logs", "data_records", "discovery_candidates"} <= tables


def test_seed(reg):
    """种子初始化: 从 catalog 迁移渠道。"""
    res = reg.seed_from_catalog()
    assert res["channels"] >= 8
    assert res["column_defs"] > 0
    assert res["errors"] == []


def test_register_custom_channel(reg, store):
    """注册自定义渠道 + 列定义 + 参数。"""
    cid = "test_channel"
    reg.register_channel({
        "channel_id": cid, "name": "测试渠道", "kind": "http_api",
        "data_classes": ["stock"], "regions": ["CN"], "status": "active",
        "source": "https://example.com/api", "method": "http_get",
    })
    assert reg.get_channel(cid)["channel_id"] == cid
    reg.add_column_def(cid, "date", "ts", "datetime", "日期")
    reg.add_column_def(cid, "close", "close", "float", "收盘")
    defs = reg.list_column_defs(cid)
    assert len(defs) == 2
    reg.set_param(cid, "interval", "5m", scope="channel")
    assert reg.param_dict(cid)["interval"] == "5m"


def test_fetch_manual_channel(reg, store):
    """manual 渠道获取 -> 数据落库。"""
    cid = "manual"
    reg.set_param(cid, "manual_rows", [
        {"date": "2026-08-01", "close": 100.0, "title": "测试1"},
        {"date": "2026-08-02", "close": 101.0, "title": "测试2"},
    ], scope="channel")
    from finance.crawler.dispatcher import fetch_channel
    res = fetch_channel(cid, instrument_id="MACRO.US.CPI", store=store)
    assert res["ok"]
    assert res["total_records"] >= 1
    ds = DataStore(store)
    assert ds.count() >= 1


def test_fetch_akshare_demo(store):
    """akshare 获取 (无依赖自动降级 demo) -> 数据落库。"""
    from finance.crawler.dispatcher import fetch_channel
    res = fetch_channel("akshare", instrument_id="CN.RB", time_level="1d", store=store)
    assert res["ok"]
    assert res["total_records"] > 0
    rows = DataStore(store).query(channel_id="akshare", instrument_id="CN.RB")
    assert len(rows) > 0
    assert rows[0]["close"] is not None


def test_tasks_add_run(store):
    """自动获取任务: add -> run-all。"""
    tm = TaskManager(store)
    tid = tm.add("akshare", instrument_id="CN.RB", time_level="1d", every="1d")
    tasks = tm.list(enabled=True)
    assert any(t["task_id"] == tid for t in tasks)
    results = tm.run_all()
    assert any(r["ok"] for r in results)


def test_tasks_partial_update(store):
    """部分字段更新不丢其它列。"""
    tm = TaskManager(store)
    tasks = tm.list(enabled=True)
    t = tasks[0]
    store.upsert("fetch_tasks", [{"task_id": t["task_id"], "last_status": "ok"}], "task_id")
    t2 = tm.get(t["task_id"])
    assert t2["channel_id"] == t["channel_id"]  # 其它列未丢
    assert t2["last_status"] == "ok"


def test_discovery_pipeline(store):
    """渠道挖掘: discover -> evaluate -> promote。"""
    d = ChannelDiscovery(store)
    # 用种子扩展引擎 (不依赖网络)
    found = d.discover(engines=["seed_expansion"])
    assert len(found) >= 1
    evals = d.evaluate()
    assert len(evals) >= 1
    # 转正第一个评分 >= 30 的
    target = next((e for e in evals if e["score"] >= 30), None)
    if target:
        res = d.promote(target["candidate_id"], channel_id="promoted_test")
        assert res["ok"]
        assert d.get_candidate(target["candidate_id"])["status"] == "promoted"


def test_logs(store):
    """运行日志。"""
    lg = RunLogger(store)
    lg.log("test", status="ok", message="测试日志", channel_id="akshare", rows_count=5)
    recent = lg.recent(run_type="test")
    assert any(r["message"] == "测试日志" for r in recent)


def test_data_stats(store):
    """数据统计。"""
    ds = DataStore(store)
    stats = ds.stats()
    assert stats["total"] >= 1
    assert "by_channel" in stats


def test_query_records(store):
    """数据查询过滤。"""
    from finance.crawler.dispatcher import query_records
    rows = query_records(store, channel_id="akshare")
    assert isinstance(rows, list)
