"""reserve 储备库管道测试 (pytest 风格, 无第三方测试框架也可直接运行)。

覆盖:
  - preprocessor: 归一化 / 去重
  - classifier: 打分 / 三分类 / 功能索引
  - embedding: 本地嵌入
  - store: LanceDB 入库 / 检索 / needs
  - trigger: 三级决策 / needs 回路
  - ingest: 端到端 (mock 快照)
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

from reserve.preprocessor import normalize_repo, dedupe, load_snapshot
from reserve.classifier import classify, classify_batch, score_repo, load_rules
from reserve.embedding import embed_text, embed_repo
from reserve.store import ReserveStore
from reserve.trigger import trigger, rematch_pending_needs
from reserve.llm import load_config, get_provider, LLMProvider, _parse_json
from reserve.enrich import enrich_one, enrich_repos
from reserve.review import review_one, review_action_candidates, queue_list, queue_update

# LanceDB 测试用临时目录 (避免污染仓库默认 reserve_data)
TEST_LANCE = Path(tempfile.mkdtemp(prefix="reserve-test-"))


def make_repo(full_name="owner/demo", stars=100, delta_7d=0, delta_24h=0,
              new=False, desc="a demo repo for testing", tags=None, created=None):
    created = created or (datetime.now(timezone.utc) - timedelta(days=2 if new else 300)).isoformat()
    return {
        "repo_id": full_name, "full_name": full_name, "name": full_name.split("/")[1],
        "owner": full_name.split("/")[0], "url": f"https://github.com/{full_name}",
        "description": desc, "language": "Python", "topics": ["ai", "mcp"] if tags is None else tags,
        "stars": stars, "forks": 10, "stars_delta_24h": delta_24h, "stars_delta_7d": delta_7d,
        "forks_delta_7d": 0, "delta_window_days": 7, "is_new_this_week": new,
        "created_at": created, "pushed_at": datetime.now(timezone.utc).isoformat(),
        "first_seen_at": datetime.now(timezone.utc).isoformat(), "source": ["test"],
        "category": "mcp-servers", "action_candidate": new or delta_7d > 0,
        "delta_source": "test", "is_secondary": False,
        "license": "MIT", "archived": False,
        "function_tags": [], "function_summary": None, "use_case": None, "ecosystem_fit": None,
    }


def store() -> ReserveStore:
    # 每个测试独立目录, 避免测试间数据干扰
    return ReserveStore(str(Path(tempfile.mkdtemp(prefix="reserve-test-"))))


# ---------- preprocessor ----------

def test_normalize_repo():
    r = normalize_repo({"full_name": "a/b", "stargazers_count": 5, "description": "hi"})
    assert r["repo_id"] == "a/b"
    assert r["stars"] == 5
    assert r["description"] == "hi"
    assert r["is_new_this_week"] is False


def test_dedupe():
    repos = [make_repo("a/b", stars=10), make_repo("a/b", stars=20), make_repo("c/d")]
    result = dedupe(repos, store=None)
    assert len(result["records"]) == 2  # a/b 保留最高 star
    by_name = {r["full_name"]: r for r in result["records"]}
    assert by_name["a/b"]["stars"] == 20
    assert len(result["new"]) == 2  # 无储备库时全部 new


# ---------- classifier ----------

def test_classifier_action():
    repo = make_repo("hot/mcp-burst", stars=15000, delta_7d=5000, delta_24h=800, desc="MCP server for AI agents")
    rules = load_rules()
    cls = classify(repo, rules)
    assert cls["category_decision"] == "action"
    assert cls["decision_score"] >= 7
    assert "MCP" in cls["function_tags"] or "AI-Agent" in cls["function_tags"]


def test_classifier_ignore():
    repo = make_repo("toy/old", stars=5, delta_7d=0, desc="unrelated game", tags=["game"])
    rules = load_rules()
    cls = classify(repo, rules)
    assert cls["category_decision"] == "ignore"


def test_classifier_reserve():
    repo = make_repo("mid/tool", stars=5000, delta_7d=100, delta_24h=50, desc="rag vector database library")
    rules = load_rules()
    cls = classify(repo, rules)
    assert cls["category_decision"] in ("reserve", "partial")
    assert cls["function_summary"]  # 功能索引已生成


# ---------- embedding ----------

def test_embedding():
    e1 = embed_text("需要 RAG 向量检索能力")
    e2 = embed_text("rag vector retrieval")
    e3 = embed_text("game engine graphics")
    assert len(e1) == 384
    # 语义相近的向量距离应小于无关的
    import math
    d_same = sum((a - b) ** 2 for a, b in zip(e1, e2)) ** 0.5
    d_diff = sum((a - b) ** 2 for a, b in zip(e1, e3)) ** 0.5
    assert d_same < d_diff


# ---------- store ----------

def test_store_upsert_search():
    s = store()
    repos = [
        make_repo("test/mcp-server", stars=1000, delta_7d=500, desc="a mcp server for github automation"),
        make_repo("test/rag-kb", stars=2000, delta_7d=100, desc="rag knowledge base with vector search"),
    ]
    # 先分类再入库 (入库不自动分类)
    from reserve.classifier import classify
    repos = [classify(r) for r in repos]
    from reserve.embedding import embed_repo
    for r in repos:
        r["embedding"] = embed_repo(r)
    stats = s.upsert_repos(repos)
    assert stats["inserted"] == 2
    assert s.count() == 2
    # 再次入库 -> update
    stats2 = s.upsert_repos(repos)
    assert stats2["updated"] == 2
    assert s.count() == 2
    # FTS 检索
    fts = s.search_fts("mcp server")
    assert len(fts) >= 1
    # 向量检索
    vec = s.search_vector(embed_repo(repos[0]))
    assert len(vec) >= 1
    # 过滤
    q = s.query(where="category_decision = 'reserve'")
    assert len(q) >= 1
    # get / delete
    assert s.get_repo("test/mcp-server") is not None
    assert s.delete_repo("test/mcp-server") is True
    assert s.get_repo("test/mcp-server") is None


def test_store_needs():
    s = store()
    s.needs_put([{"id": "n1", "text": "需要 MCP 工具", "keywords": ["mcp"], "status": "open"}])
    needs = s.needs_get()
    assert len(needs) == 1
    assert needs[0]["id"] == "n1"


# ---------- trigger ----------

def test_trigger_log_and_rematch():
    s = store()
    # 空库 -> LOG + 记录 need
    res = trigger("需要一个量子计算模拟器", top_k=3, store=s)
    assert res["level"] == "LOG"
    needs = s.needs_get()
    assert len(needs) == 1
    # 入库一个匹配项目 -> rematch 命中
    repo = make_repo("quantum/sim", stars=500, delta_7d=100,
                     desc="quantum computing simulator engine", tags=["quantum", "simulator"])
    from reserve.classifier import classify
    from reserve.embedding import embed_repo
    repo = classify(repo)
    repo["embedding"] = embed_repo(repo)
    s.upsert_repos([repo])
    results = rematch_pending_needs(s)
    assert len(results) >= 1
    # need 状态变为 matched
    needs2 = s.needs_get()
    assert any(n["status"] == "matched" for n in needs2)


def test_trigger_auto():
    s = store()
    repo = make_repo("agentenv/mcp-agent", stars=3000, delta_7d=2000,
                     desc="MCP agent framework for AI tools orchestration")
    from reserve.classifier import classify
    from reserve.embedding import embed_repo
    repo = classify(repo)
    repo["embedding"] = embed_repo(repo)
    s.upsert_repos([repo])
    res = trigger("MCP agent 智能体工具", top_k=5, store=s)
    assert res["level"] in ("AUTO", "SUGGEST")


# ---------- ingest 端到端 ----------

def test_ingest_end_to_end():
    from reserve.ingest import run
    snap = ROOT / "pipeline" / "data" / "snapshots" / "test-e2e.json"
    repos = [
        make_repo("e2e/action-mcp", stars=20000, delta_7d=8000, delta_24h=1000, new=True,
                  desc="MCP server framework for AI agent ecosystem"),
        make_repo("e2e/ignore-game", stars=3, delta_7d=0, desc="a simple game"),
    ]
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps({"date": "test-e2e", "repos": repos}), encoding="utf-8")
    os.environ["LANCE_DIR"] = str(TEST_LANCE)
    result = run(snap, dry_run=True)
    assert result["dry_run"] is True
    assert result["new"] == 2
    assert result["decisions"].get("action", 0) >= 1
    snap.unlink()


# ---------- LLM Provider / 功能索引 / 代码审核 ----------

class _FakeProvider:
    """模拟 LLM provider (不依赖真实模型/网络)。"""

    def __init__(self, reply: dict | str | None):
        self.reply = reply

    def complete_json(self, system: str, user: str) -> dict | None:
        if isinstance(self.reply, dict):
            return json.loads(json.dumps(self.reply))
        if isinstance(self.reply, str):
            return _parse_json(self.reply)
        return None

    def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        return json.dumps(self.reply, ensure_ascii=False) if isinstance(self.reply, dict) else self.reply


def test_llm_parse_json():
    # 直接 JSON
    assert _parse_json('{"a": 1}') == {"a": 1}
    # 代码块包裹
    assert _parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    # 前后有杂音文本
    out = _parse_json('好的，结果如下：{"a": 3} 完')
    assert out == {"a": 3}
    # 非法
    assert _parse_json('no json here') is None


def test_llm_config_defaults():
    # 未配置任何 LLM 环境变量时, provider=None (启发式兑底路径)
    import os
    for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
              "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OPENAI_API_KEY", "EMBEDDING_API_KEY"):
        os.environ.pop(k, None)
    cfg = load_config()
    assert cfg["provider"] == "auto"
    assert get_provider() is None or get_provider().provider in ("openai", "ollama")


def test_enrich_fake_provider():
    repo = make_repo("llm/mcp-tool", desc="mcp server for git automation")
    fake = _FakeProvider({
        "function_tags": ["MCP", "AI-Agent"],
        "function_summary": "一个 MCP 服务器, 用于 GitHub 自动化",
        "use_case": "需要 MCP 服务接入 GitHub 自动化时使用",
        "ecosystem_fit": "强匹配 MCP 生态",
    })
    out = enrich_one(repo, readme="# my mcp tool\nIt does git automation.", provider=fake)
    assert out["function_tags"] == ["MCP", "AI-Agent"]
    assert out["index_source"] == "llm"
    assert "GitHub" in out["function_summary"]


def test_enrich_no_provider_keeps_heuristic():
    # 无 provider 时不改仓库 (classifier 启发式兑底保留)
    repo = make_repo("heuristic/rag", desc="rag vector database")
    before = dict(repo)
    out = enrich_one(repo, provider=None)
    assert out["function_tags"] == before["function_tags"]


def test_enrich_batch_skips_existing_index():
    repo = make_repo("skip/already", desc="already indexed")
    repo["function_tags"] = ["已有标签"]
    fake = _FakeProvider({"function_tags": ["MCP"], "function_summary": "x",
                          "use_case": "y", "ecosystem_fit": "z"})
    out = enrich_repos([repo], fetch_readme=False, progress=False)
    # use_cache=True 默认: 已有 function_tags 跳过
    assert out[0]["function_tags"] == ["已有标签"]


def test_review_fake_provider():
    repo = make_repo("review/mcp-hot", stars=20000, delta_7d=5000,
                     desc="MCP server for AI agents")
    fake = _FakeProvider({
        "verdict": "approve",
        "score": 8,
        "risks": ["依赖较重"],
        "recommendation": "质量高, 可吸收",
    })
    rv = review_one(repo, readme="# mcp hot\nfull docs", provider=fake)
    assert rv is not None
    assert rv["verdict"] == "approve"
    assert rv["score"] == 8


def test_review_no_provider_goes_queue():
    # 无 provider 时 action 候选直接进人工审核队列
    os.environ["REVIEW_QUEUE"] = str(Path(tempfile.mkdtemp(prefix="review-q-")) / "queue.json")
    import reserve.review as review_mod
    review_mod.QUEUE_PATH = Path(os.environ["REVIEW_QUEUE"])
    repo = make_repo("queue/action-cand", stars=5000, delta_7d=3000,
                     desc="MCP agent tool")
    repo["category_decision"] = "action"
    review_action_candidates([repo], fetch_readme=False)
    q = queue_list()
    assert len(q) >= 1
    assert q[0]["full_name"] == "queue/action-cand"
    assert q[0]["status"] == "pending"
    # 更新状态
    entry = queue_update("queue/action-cand", "approved", note="ok")
    assert entry is not None and entry["status"] == "approved"
    os.environ.pop("REVIEW_QUEUE", None)
    review_mod.QUEUE_PATH = Path(__file__).resolve().parent.parent / "config" / "review_queue.json"


# ---------- 能力聚类 (cluster) ----------

def test_cluster_by_tags():
    from reserve.cluster import cluster_by_tags
    repos = [
        make_repo("a/rag1", desc="rag engine", tags=["rag", "vector"]),
        make_repo("b/rag2", desc="another rag", tags=["rag"]),
        make_repo("c/mcp1", desc="mcp server", tags=["mcp"]),
    ]
    from reserve.classifier import classify
    repos = [classify(r) for r in repos]
    result = cluster_by_tags(repos)
    assert result["mode"] == "by-tags"
    assert result["summary"]["total_repos"] == 3
    tags = [c["tag"] for c in result["clusters"]]
    assert any("RAG" in t for t in tags)


def test_cluster_kmeans():
    from reserve.cluster import kmeans
    from reserve.classifier import classify
    repos = [classify(make_repo(f"km/r{i}", desc=d, tags=t))
             for i, (d, t) in enumerate([
                 ("rag vector search engine", ["rag"]),
                 ("rag knowledge base", ["rag", "kb"]),
                 ("mcp server tool", ["mcp"]),
                 ("mcp agent framework", ["mcp", "agent"]),
                 ("game engine", ["game"]),
             ])]
    result = kmeans(repos, k=3)
    assert result["mode"] == "kmeans"
    assert result["summary"]["total_repos"] == 5
    assert len(result["clusters"]) >= 1


# ---------- numpy 清洗 (store 读回) ----------

def test_store_rows_to_dicts_numpy_clean():
    """LanceDB 读回的行应把 numpy array/标量转回原生类型 (下游 if not tags / json 不炸)。"""
    import tempfile
    from reserve.store import ReserveStore
    from reserve.classifier import classify
    from reserve.embedding import embed_repo
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="np-clean-"))))
    repo = classify(make_repo("np/clean", desc="mcp server", tags=["mcp"]))
    repo["embedding"] = embed_repo(repo)
    s.upsert_repos([repo])
    rows = s.all_repos()
    assert len(rows) == 1
    r = rows[0]
    # numpy ndarray 已被清洗为 list
    assert isinstance(r.get("function_tags"), list)
    assert isinstance(r.get("embedding"), list)
    assert isinstance(r.get("stars"), int)
    # 布尔/数值可安全使用
    assert not r.get("archived") or isinstance(r.get("archived"), bool)


# ---------- main ----------

def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, []
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed.append(t.__name__)
    print(f"\n{passed}/{len(tests)} passed")
    if failed:
        print(f"failed: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------- quality (质量评估) ----------

def test_quality_assess_snapshot():
    """快照质量评估: demo 快照可评估, 有 score/grade/issues。"""
    from reserve.quality import assess_snapshot
    rep = assess_snapshot(ROOT / "pipeline" / "data" / "snapshots" / "demo-2026-08-08.json")
    assert "error" not in rep, rep
    assert 0 <= rep["score"] <= 100
    assert rep["grade"]["grade"] in ("A", "B", "C", "D")
    assert rep["stats"]["total"] == 5
    assert rep["stats"]["unique"] == 5
    assert rep["stats"]["missing_fields"]["stars"] == 0  # v1 字段兼容 (stargazers_count)


def test_quality_assess_store():
    """储备库质量评估。"""
    from reserve.quality import assess_store
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="quality-store-"))))
    r = classify(make_repo("q/a", desc="mcp server", tags=["mcp"]))
    r["embedding"] = embed_repo(r)
    s.upsert_repos([r])
    rep = assess_store(s)
    assert 0 <= rep["score"] <= 100
    assert rep["stats"]["total"] == 1


def test_quality_trend():
    """多日趋势: 兼容 demo-YYYY-MM-DD 命名。"""
    from reserve.quality import assess_trend
    snap_dir = ROOT / "pipeline" / "data" / "snapshots"
    rep = assess_trend(days=7, snapshots_dir=snap_dir)
    assert "error" not in rep, rep
    assert rep["days"] >= 1
    assert isinstance(rep["points"], list)
    assert rep["points"][0]["date"]  # demo-2026-08-08


def test_quality_report():
    """综合报告生成并写盘。"""
    from reserve.quality import build_report, write_report
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="quality-report-"))))
    rep = build_report(days=7, store=s, snapshot=ROOT / "pipeline" / "data" / "snapshots" / "demo-2026-08-08.json")
    assert rep["type"] == "report"
    assert rep["overall_score"] >= 0
    out = write_report(rep, path=Path(tempfile.mkdtemp()) / "report.json")
    assert out.exists()


# ---------- self_heal (自愈合) ----------

def test_self_heal_health_check():
    """健康检查: 返回 checks, 只有 high 级别才判不健康。"""
    from reserve.self_heal import health_check, load_policy, save_default_policy
    save_default_policy()
    h = health_check()
    assert "checks" in h
    assert "summary" in h
    assert "snapshot_missing" in h["checks"] or "snapshot_ok" in h["checks"]


def test_self_heal_diagnose():
    """诊断: 问题映射到动作。"""
    from reserve.self_heal import diagnose
    problems = diagnose({"snapshot_missing": {"ok": False, "severity": "high", "detail": "x"},
                         "fts_index_missing": {"ok": False, "severity": "low", "detail": "y"}})
    ids = {p["id"] for p in problems}
    assert "snapshot_missing" in ids
    assert "fts_index_missing" in ids
    assert all(p["action"] in ("refetch", "ingest", "rebuild_fts", "clean_temp", "degrade", "wait") for p in problems)


def test_self_heal_log():
    """愈合日志: 追加/读取。"""
    from reserve.self_heal import IncidentLog
    log = IncidentLog(path=str(Path(tempfile.mkdtemp()) / "heal_log.json"))
    log.append({"event": "heal_test", "level": "info", "ok": True, "detail": "test"})
    entries = log.list()
    assert len(entries) == 1
    assert entries[0]["event"] == "heal_test"


def test_self_heal_rebuild_fts():
    """自愈动作: 重建 FTS 索引。"""
    from reserve.self_heal import heal_rebuild_fts
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="heal-fts-"))))
    r = classify(make_repo("h/f", desc="mcp server", tags=["mcp"]))
    r["embedding"] = embed_repo(r)
    s.upsert_repos([r])
    result = heal_rebuild_fts(s)
    assert result["ok"] is True


# ---------- dashboard (结构化整理) ----------

def test_dashboard_overview():
    """总览视图。"""
    from reserve.dashboard import overview
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="dash-ov-"))))
    r = classify(make_repo("d/ov", desc="mcp server", tags=["mcp"]))
    r["embedding"] = embed_repo(r)
    s.upsert_repos([r])
    o = overview(store=s)
    assert o["stats"]["total_repos"] == 1
    assert "quality" in o
    assert "snapshots" in o


def test_dashboard_repos_view():
    """仓库列表视图: 过滤/排序。"""
    from reserve.dashboard import repos_view
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="dash-repos-"))))
    r1 = classify(make_repo("d/r1", stars=100, desc="mcp server", tags=["mcp"]))
    r2 = classify(make_repo("d/r2", stars=500, desc="rag knowledge", tags=["rag"]))
    for r in (r1, r2):
        r["embedding"] = embed_repo(r)
    s.upsert_repos([r1, r2])
    v = repos_view(store=s, limit=10, sort="stars")
    assert v["total"] == 2
    assert v["items"][0]["full_name"] == "d/r2"  # stars 排序
    v2 = repos_view(store=s, q="rag")
    assert v2["total"] == 1
    assert v2["items"][0]["full_name"] == "d/r2"


def test_dashboard_clusters_view():
    """能力簇视图。"""
    from reserve.dashboard import clusters_view
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="dash-clu-"))))
    r = classify(make_repo("d/c", desc="mcp server", tags=["mcp"]))
    r["embedding"] = embed_repo(r)
    s.upsert_repos([r])
    c = clusters_view(store=s, mode="by-tags")
    assert "clusters" in c
    assert c.get("summary", {}).get("total_repos", 0) >= 1


def test_dashboard_quality_view():
    """质量视图。"""
    from reserve.dashboard import quality_view
    s = ReserveStore(str(Path(tempfile.mkdtemp(prefix="dash-qual-"))))
    q = quality_view(days=7, store=s, snapshot=ROOT / "pipeline" / "data" / "snapshots" / "demo-2026-08-08.json")
    assert q["type"] == "report"
    assert q["overall_score"] >= 0


# ---------- API 路由 (v3) ----------

def test_api_routes_registered():
    """API v3 路由: 验证新端点存在 (通过模拟请求处理)。"""
    import io
    from reserve import api as api_mod
    # 直接检查 do_GET 源码包含新路由 (避免起服务)
    src = open(api_mod.__file__, encoding="utf-8").read()
    for route in ("/api/v1/quality", "/api/v1/health", "/api/v1/heal/log",
                  "/api/v1/dashboard/overview", "/api/v1/dashboard/repos",
                  "/api/v1/dashboard/clusters", "/api/v1/dashboard/snapshots",
                  "/api/v1/dashboard/review", "/api/v1/dashboard/needs",
                  "_serve_static"):
        assert route in src, f"missing route: {route}"
