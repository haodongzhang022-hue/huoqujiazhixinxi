"""reserve/enrich.py — LLM 功能索引生成器（读 README / 项目发布者介绍 → 高质量索引）

用户核心诉求落地点之一：
  「这部分似乎需要引入大模型进行代码审核实现，或者看项目发布者的介绍，
    读这些也是需要大模型」

本模块让 LLM 干两件"读"的活：
  1. **功能索引**  读取仓库元数据 + README（发布者介绍）
                   → 生成 function_tags / function_summary / use_case / ecosystem_fit
                   中文输出, 对齐 LanceDB repo_reserve 表的四个功能索引字段
  2. **代码审核**  对 action 候选（生态升级）仓库做四维审核
                   （详见 reserve/review.py, 本模块只做索引增强）

无 LLM 配置时 -> enrich_repos() 自动跳过, 由 classifier 启发式兜底（原行为不变）。

用法:
  from reserve.enrich import enrich_repos, enrich_one
  enrich_repos(repos, fetch_readme=False)   # 批量增强 (可选拉取 README)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from reserve.llm import get_provider, load_config, describe_config

# 功能标签白名单 (引导 LLM 输出受控标签, 便于检索与聚合)
TAG_WHITELIST = [
    "MCP", "AI-Agent", "RAG", "LLM", "知识库", "AI-编程", "Agent编排", "工作流",
    "提示词", "推理", "训练/微调", "向量数据库", "数据管道", "数据基础设施",
    "搜索/检索", "爬虫", "API/SDK", "CLI工具", "开发者工具", "前端", "后端",
    "数据库", "中间件", "云原生", "容器", "安全", "测试", "监控/可观测",
    "部署/DevOps", "资源索引", "内容生成", "多模态", "语音", "图像",
    "自动化", "翻译", "代码审核", "文本处理", "数据分析", "可视化",
]

_SYSTEM = """你是一名资深开源技术评审专家。请根据给定的开源仓库信息（名称/描述/topics/README 内容），
判断这个项目**解决什么问题、什么场景适用、与我们生态的匹配度**，并输出严格的 JSON。

必须只输出 JSON 对象（不要 markdown 代码块、不要解释），格式：
{
  "function_tags": ["标签1", "标签2", ...],
  "function_summary": "一句话中文总结：这个项目解决什么问题（不超过 60 字）",
  "use_case": "适用场景说明（不超过 80 字，说明什么时候应该用它）",
  "ecosystem_fit": "与我们生态的匹配度分析（不超过 60 字，从 MCP/AI-Agent/RAG/LLM/数据基础设施 角度）"
}

要求：
- function_tags 最多 4 个，优先从下面白名单里选（可适当补充 1 个更精确的自定义标签）：
  MCP, AI-Agent, RAG, LLM, 知识库, AI-编程, Agent编排, 工作流, 提示词, 推理,
  训练/微调, 向量数据库, 数据管道, 数据基础设施, 搜索/检索, 爬虫, API/SDK,
  CLI工具, 开发者工具, 前端, 后端, 数据库, 中间件, 云原生, 容器, 安全, 测试,
  监控/可观测, 部署/DevOps, 资源索引, 内容生成, 多模态, 语音, 图像, 自动化,
  翻译, 代码审核, 文本处理, 数据分析, 可视化
- 全部用中文输出
- 信息不足时也要尽力从仓库名/描述推断，不要返回空 tags"""


def _repo_input(repo: dict, readme: str | None = None) -> str:
    topics = repo.get("topics") or []
    parts = [
        f"仓库名: {repo.get('full_name', '')}",
        f"语言: {repo.get('language') or '未知'}",
        f"Star: {repo.get('stars', 0)}",
        f"分类: {repo.get('category') or '通用'}",
        f"描述: {repo.get('description') or '(无)'}",
        f"主题标签: {', '.join(str(t) for t in topics) or '(无)'}",
        f"创建时间: {repo.get('created_at') or '未知'}",
        f"最近更新: {repo.get('pushed_at') or '未知'}",
    ]
    if readme:
        parts.append(f"README（发布者介绍, 截断）:\n{readme}")
    return "\n".join(parts)


def enrich_one(repo: dict, readme: str | None = None, provider=None,
               use_cache: bool = True) -> dict:
    """对单仓库做 LLM 功能索引增强（写回 repo 的四个字段）。

    - 无 provider -> 原样返回（由 classifier 启发式兜底）
    - 调用失败 -> 打印日志并原样返回（不影响管道）
    - 成功 -> 写回 function_tags / function_summary / use_case / ecosystem_fit
    """
    provider = provider or get_provider()
    if provider is None:
        return repo
    if use_cache and repo.get("function_tags"):
        return repo  # 已有索引（如来自快照/上次入库）则跳过, 省配额

    user = _repo_input(repo, readme)
    out = provider.complete_json(_SYSTEM, user)
    if not out:
        print(f"[enrich] llm index failed for {repo.get('full_name')}, keep heuristic")
        return repo

    tags = out.get("function_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    # 清洗: 字符串化 + 去重 + 截断
    clean_tags: list[str] = []
    for t in tags:
        s = str(t).strip().strip('"')
        if s and s not in clean_tags:
            clean_tags.append(s)
    if clean_tags:
        repo["function_tags"] = clean_tags[:4]
    if out.get("function_summary"):
        repo["function_summary"] = str(out["function_summary"]).strip()[:200]
    if out.get("use_case"):
        repo["use_case"] = str(out["use_case"]).strip()[:300]
    if out.get("ecosystem_fit"):
        repo["ecosystem_fit"] = str(out["ecosystem_fit"]).strip()[:200]
    repo["index_source"] = "llm"
    repo["indexed_at"] = datetime.now(timezone.utc).isoformat()
    return repo


def enrich_repos(repos: list[dict], fetch_readme: bool = False,
                 readme_provider=None, max_repos: int | None = None,
                 progress: bool = True) -> list[dict]:
    """批量 LLM 功能索引增强。

    参数:
      fetch_readme: 是否拉取 README（消耗 GitHub 配额, 每仓库 1 请求; 建议 action 候选才开）
      readme_provider: 自定义 README 获取函数 fn(full_name) -> str|None
                       （默认用 pipeline.github_client.get_readme, 便于测试注入）
      max_repos:     最多增强 N 个（None 全部）
      progress:      是否打印进度
    返回: 增强后的 repos（无 provider 时原样返回）
    """
    provider = get_provider()
    if provider is None:
        if progress:
            print(f"[enrich] 未配置 LLM, 跳过增强 (启发式兜底)。配置方法: {describe_config()}")
        return repos

    todo = repos
    if max_repos is not None:
        todo = repos[:max_repos]

    if readme_provider is None:
        try:
            from pipeline.github_client import get_readme
            readme_provider = get_readme
        except Exception:
            readme_provider = None

    done = 0
    for r in todo:
        readme = None
        if fetch_readme and readme_provider is not None:
            try:
                readme = readme_provider(r.get("full_name") or "")
            except Exception as e:
                print(f"[enrich] readme fetch failed {r.get('full_name')}: {e}")
        try:
            enrich_one(r, readme=readme, provider=provider)
        except Exception as e:
            print(f"[enrich] error {r.get('full_name')}: {e}")
        if r.get("index_source") == "llm":
            done += 1
        if progress and (done == 0 or done % 5 == 0):
            print(f"[enrich] llm-indexed {done}/{len(todo)}")
    if progress:
        print(f"[enrich] done: llm-indexed {done}/{len(todo)}")
    return repos


if __name__ == "__main__":
    import argparse
    import sys

    from reserve.llm import save_default_config

    save_default_config()
    parser = argparse.ArgumentParser(description="LLM 功能索引增强")
    parser.add_argument("input", help="快照/归一化 JSON")
    parser.add_argument("--out", default=None, help="输出 JSON")
    parser.add_argument("--readme", action="store_true", help="拉取 README 增强")
    parser.add_argument("--max", type=int, default=None, help="最多增强 N 个")
    args = parser.parse_args()

    from pathlib import Path
    from reserve.preprocessor import load_snapshot

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"input not found: {in_path}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(in_path.read_text(encoding="utf-8"))
    repos = data.get("repos") or data.get("items") or data if isinstance(data, dict) else data
    if isinstance(repos, dict):
        repos = list(repos.values())

    out_repos = enrich_repos(repos, fetch_readme=args.readme, max_repos=args.max)
    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + ".enriched.json")
    out_path.write_text(json.dumps({"date": in_path.stem, "repos": out_repos},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(out_repos)} repos)")
    sys.exit(0)
