"""生态分类与查询配置 —— 泛化自 wvb-cc-radar 的 8 分类分层查询模型。

设计来源:
  https://github.com/drwon-cmd/wvb-cc-radar (scripts/fetch.py, v0.6)

核心模型 = T1/T2/T3 三层防漏查询:
  T1 (trending, 14d window)      : topic / name / description 匹配 —— "正在热"的信号
  T2 (stable viral, 60d window)  : README 匹配 + stars 门槛 —— 稳定期 viral 捕获
                                   (绕过"无 topic + name 不匹配 + desc 无关键词"的 4 重漏检)
  T3 (permanent viral, no cutoff): topic 匹配 + 高 stars 门槛 —— 长周期稳定命中

每类还支持 `seed_queries`: 显式 allowlist (data/seeds/*.json)，
对 search 抓不到但明确值得跟踪的仓库做 /repos 直连强制纳入。

分类从 wvb-cc-radar 的 Claude Code 专属生态泛化为通用技术生态
(覆盖 MCP / Agent / RAG / 编排 / 提示词 / AI 工具 / 数据基础设施 / 开发者工具)，
与本地 LanceDB 储备库 repo_reserve 表的 8 分类对齐。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

# ============================================================
# 时间窗口
# ============================================================

RECENT_DAYS = 14   # T1: 14 天内 pushed
STABLE_DAYS = 60   # T2: 60 天内 pushed
NEW_DAYS = 7       # T4: 7 天内 created —— 新仓库扫描 (action 冷启动信号)


def recent_date(days: int) -> str:
    """返回 N 天前的 YYYY-MM-DD (UTC)，用于 pushed:> 过滤。"""
    d = datetime.now(timezone.utc) - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _t1() -> str:
    return f" pushed:>{recent_date(RECENT_DAYS)}"


def _t2() -> str:
    return f" pushed:>{recent_date(STABLE_DAYS)}"


def _t3() -> str:
    return ""  # 无 pushed 截止 —— 永久捕获稳定期大仓库


def _t4() -> str:
    """T4 新仓库扫描: created 窗口内的新项目。

    新仓库没有历史快照, stars_delta 无法由基线计算 → 冷启动下 action 路径瘫痪。
    增加 created:> 窗口查询, 让 fetch 主动捕获当周新项目,
    配合 fetch.py 的冷启动推断 (is_new_this_week → stars_delta_7d ≈ stars) 激活 action。
    """
    d = datetime.now(timezone.utc) - timedelta(days=NEW_DAYS)
    return f" created:>{d.strftime('%Y-%m-%d')}"


# ============================================================
# 生态分类 (8 类, 合计 ~100 仓库/日)
# ============================================================

def categories(seeds: dict[str, list[str]]) -> list[dict]:
    """构造分类配置。

    seeds: {category_id: [full_name, ...]} —— 从 data/seeds/*.json 读取，
           每类可选的显式 allowlist，会被转成 `repo:{fn}` 直连查询。
    """
    s = _t1()
    sl = _t2()
    s3 = _t3()
    s4 = _t4()
    return [
        {
            "id": "mcp-servers",
            "title": "MCP 服务器与工具",
            "subtitle": "Model Context Protocol servers & tools",
            "queries": [
                # T1 trending
                "topic:model-context-protocol" + s,
                '"mcp-server" in:name' + s,
                '"mcp-servers" in:name' + s,
                # T2 README match (60d) —— MCP topic 未标注的 server 捕获
                '"is an MCP server" in:readme stars:>500' + sl,
                # T3 stable viral
                "topic:model-context-protocol stars:>10000",
                # T4 new repos (created 7d)
                "topic:model-context-protocol stars:>100" + s4,
                '"mcp-server" in:name stars:>50' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("mcp-servers", [])],
            "top_n": 12,
            "priority": 1,
        },
        {
            "id": "ai-agents",
            "title": "AI 代理框架",
            "subtitle": "LangGraph · CrewAI · AutoGen · multi-agent framework",
            "queries": [
                # T1 trending
                "topic:ai-agents" + s,
                '"langgraph" in:name' + s,
                '"crewai" in:name' + s,
                '"autogen" in:name' + s,
                # T2 README match (60d)
                '"multi-agent framework" in:readme stars:>10000' + sl,
                # T3 stable viral
                "topic:ai-agents stars:>30000",
                # T4 new repos (created 7d)
                "topic:ai-agents stars:>100" + s4,
                '"agent" in:name stars:>100' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("ai-agents", [])],
            "top_n": 12,
            "priority": 2,
        },
        {
            "id": "rag-kb",
            "title": "RAG 与知识库",
            "subtitle": "LLM knowledge base, retrieval-augmented generation, wiki 自动化",
            "queries": [
                # T1 trending
                "topic:rag" + s,
                "topic:retrieval-augmented-generation" + s,
                '"knowledge-base" in:name' + s,
                # T2 README match (60d)
                '"retrieval augmented generation" in:readme stars:>2000' + sl,
                # T3 stable viral
                "topic:rag stars:>10000",
                # T4 new repos (created 7d)
                "topic:rag stars:>100" + s4,
                '"knowledge-base" in:name stars:>50' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("rag-kb", [])],
            "top_n": 12,
            "priority": 3,
        },
        {
            "id": "agent-orchestration",
            "title": "Agent 编排与路由",
            "subtitle": "Multi-agent coordinator, handoff patterns, agent routing",
            "queries": [
                # T1 trending
                "topic:multi-agent" + s,
                "topic:agent-orchestration" + s,
                '"orchestrator" in:name' + s,
                # T3 stable viral
                "topic:multi-agent stars:>20000",
                # T4 new repos (created 7d)
                "topic:multi-agent stars:>50" + s4,
                '"orchestrator" in:name stars:>30' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("agent-orchestration", [])],
            "top_n": 10,
            "priority": 4,
        },
        {
            "id": "llm-prompts",
            "title": "LLM 提示词与工作流",
            "subtitle": "Prompt engineering · agentic workflows · LLM-native dev",
            "queries": [
                # T1 trending
                "topic:prompt-engineering" + s,
                "topic:agentic-workflow" + s,
                '"prompt-engineering" in:name' + s,
                # T3 stable viral (如 Prompt-Engineering-Guide 65d 停滞大仓库)
                "topic:prompt-engineering stars:>20000",
                # T4 new repos (created 7d)
                "topic:prompt-engineering stars:>50" + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("llm-prompts", [])],
            "top_n": 10,
            "priority": 5,
        },
        {
            "id": "ai-dev-tools",
            "title": "AI 开发工具与 IDE",
            "subtitle": "Claude Code 生态 · Cursor/Bolt 系 · AI coding / AI IDE",
            "queries": [
                # T1 trending
                "topic:ai-coding" + s,
                "topic:ai-ide" + s,
                '"ai-coding" in:name' + s,
                "topic:claude-code" + s,
                '"claude-code" in:name' + s,
                # T2 README match (60d)
                '"with claude code" in:readme stars:>5000' + sl,
                # T3 stable viral
                "topic:claude-code stars:>50000",
                # T4 new repos (created 7d)
                "topic:ai-coding stars:>50" + s4,
                '"claude-code" in:name stars:>30' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("ai-dev-tools", [])],
            "top_n": 12,
            "priority": 6,
        },
        {
            "id": "data-infra",
            "title": "数据与向量基础设施",
            "subtitle": "vector database · data infrastructure · 检索/存储引擎",
            "queries": [
                # T1 trending
                "topic:vector-database" + s,
                "topic:data-infrastructure" + s,
                '"vectordb" in:name' + s,
                # T2 README match (60d)
                '"vector database" in:readme stars:>1000' + sl,
                # T3 stable viral
                "topic:vector-database stars:>5000",
                # T4 new repos (created 7d)
                "topic:vector-database stars:>50" + s4,
                '"vectordb" in:name stars:>30' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("data-infra", [])],
            "top_n": 10,
            "priority": 7,
        },
        {
            "id": "developer-tools",
            "title": "开发者工具与开源库",
            "subtitle": "CLI · awesome-list · developer-tools · 高质量开源库",
            "queries": [
                # T1 trending
                "topic:developer-tools stars:>500" + s,
                "topic:cli stars:>1000" + s,
                '"awesome" in:name stars:>2000' + s,
                # T2 README match (60d)
                '"command line" in:readme stars:>3000' + sl,
                # T3 stable viral
                "topic:developer-tools stars:>20000",
                # T4 new repos (created 7d)
                "topic:developer-tools stars:>100" + s4,
                '"awesome" in:name stars:>100' + s4,
            ],
            "seed_queries": [f"repo:{fn}" for fn in seeds.get("developer-tools", [])],
            "top_n": 12,
            "priority": 8,
        },
    ]
