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
