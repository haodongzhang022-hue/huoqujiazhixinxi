"""向量化 (embedding.py) —— 生成仓库 embedding 用于 LanceDB 向量检索。

策略:
  1. EMBEDDING_API_KEY / OPENAI_API_KEY 存在 -> 调用 API embedding (维度更高)
  2. 否则 -> 本地 TF 哈希嵌入 (384 维, 零依赖, 中英文混合可用)

本地嵌入说明:
  基于字符/词元 hash 的稀疏向量 -> 归一化到 384 维。
  对中英文混合文本有效 (中文按字 bigram, 英文按词), 可支撑语义近似检索
  (如 "需要 RAG 向量检索能力" 与仓库描述含 rag/vector 的记录相似度高)。

生产建议: 配置 OPENAI_API_KEY 或 EMBEDDING_API_URL 使用更强的 embedding 模型。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request

EMBED_DIM = 384

# ============================================================
# 中英术语映射 (跨语言匹配桥接)
# 纯中文需求与英文仓库描述匹配的核心: 把中文术语扩展为英文同义词 token
# ============================================================

ZH_EN_MAP = {
    "量子": ["quantum"],
    "计算": ["compute", "computing", "calculator"],
    "模拟": ["simulate", "simulation", "simulator"],
    "模拟器": ["simulator"],
    "智能": ["intelligence", "ai"],
    "智能体": ["agent"],
    "代理": ["agent", "proxy"],
    "机器人": ["robot", "bot"],
    "知识": ["knowledge"],
    "知识库": ["knowledge-base", "knowledge"],
    "检索": ["retrieval", "search", "index"],
    "向量": ["vector", "embedding"],
    "嵌入": ["embedding", "embed"],
    "数据库": ["database", "db", "sql"],
    "向量库": ["vector-db", "vectordb"],
    "搜索": ["search", "index"],
    "框架": ["framework"],
    "工具": ["tool", "cli"],
    "命令": ["command", "cli"],
    "提示": ["prompt"],
    "提示词": ["prompt"],
    "翻译": ["translate", "translation"],
    "对话": ["chat", "conversation", "dialog"],
    "问答": ["qa", "question"],
    "推理": ["inference", "reason"],
    "训练": ["train", "training"],
    "模型": ["model", "llm"],
    "大模型": ["llm", "model"],
    "文本": ["text", "nlp"],
    "代码": ["code", "coding"],
    "编程": ["coding", "programming"],
    "生成": ["generate", "generation"],
    "图片": ["image"],
    "图像": ["image", "vision"],
    "视频": ["video"],
    "音频": ["audio", "speech"],
    "语音": ["speech", "voice", "asr"],
    "工作流": ["workflow", "pipeline"],
    "编排": ["orchestration", "orchestrator"],
    "路由": ["routing", "router"],
    "监控": ["monitor", "observability"],
    "日志": ["log", "logging"],
    "测试": ["test", "testing"],
    "部署": ["deploy", "deployment"],
    "容器": ["container", "docker"],
    "云": ["cloud"],
    "安全": ["security"],
    "爬虫": ["crawler", "spider", "scrape"],
    "抓取": ["crawl", "scrape", "fetch"],
    "文档": ["document", "docs"],
    "文档库": ["docs", "documentation"],
    "分析": ["analy", "analysis"],
    "数据": ["data"],
    "可视化": ["visualization", "visualize", "chart"],
    "图表": ["chart", "graph"],
    "接口": ["api", "sdk"],
    "应用": ["app", "application"],
    "平台": ["platform"],
    "网关": ["gateway"],
    "插件": ["plugin", "extension"],
    "扩展": ["extension", "plugin"],
    "生态": ["ecosystem"],
    "资源": ["resource", "awesome", "list"],
    "索引": ["index", "catalog"],
    "目录": ["catalog", "directory", "list"],
    "压缩": ["compress", "token"],
    "标记": ["token"],
    "token": ["token"],
    "开源": ["open-source", "oss"],
    "协议": ["protocol", "license"],
    "标准": ["standard"],
}


# ============================================================
# 文本 -> 词元
# ============================================================

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _zh_aliases(cjk_chars: list[str]) -> list[str]:
    """中文序列 -> 中英别名: 尝试整句/大块匹配, 再逐字 bigram 查表。"""
    aliases: list[str] = []
    text = "".join(cjk_chars)
    # 优先最长匹配 (贪心)
    keys = sorted(ZH_EN_MAP.keys(), key=len, reverse=True)
    rest = text
    i = 0
    while i < len(rest):
        matched = False
        for k in keys:
            if rest.startswith(k):
                aliases.extend(ZH_EN_MAP[k])
                i += len(k)
                rest = rest[len(k):]
                matched = True
                break
        if not matched:
            i += 1
            rest = rest[1:]
    return aliases


def tokenize(text: str) -> list[str]:
    """中英文混合分词: 英文小写单词 + 中文 bigram + 中英别名扩展。"""
    text = text.lower()
    tokens: list[str] = []
    # 英文/数字词
    tokens.extend(_WORD_RE.findall(text))
    # 中文 bigram
    cjk = _CJK_RE.findall(text)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    if len(cjk) == 1:
        tokens.append(cjk[0])
    # 中英别名扩展 (中文术语 -> 英文同义词)
    if cjk:
        tokens.extend(_zh_aliases(cjk))
    return tokens


def _hash_token(token: str, dim: int) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """本地 TF hash 嵌入 (无监督, 确定性, 中英桥接)。"""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for t in tokens:
        vec[_hash_token(t, dim)] += 1.0
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def build_repo_text(repo: dict) -> str:
    """把仓库记录拼接为 embedding 输入文本 (含中文别名扩展)。"""
    parts = [
        repo.get("name", ""),
        repo.get("full_name", ""),
        repo.get("description", "") or "",
        repo.get("description_zh", "") or "",
        repo.get("function_summary", "") or "",
        repo.get("use_case", "") or "",
        " ".join(repo.get("topics", []) or []),
        " ".join(repo.get("function_tags", []) or []),
        repo.get("category", "") or "",
    ]
    text = " ".join(filter(None, parts))
    # 中文别名扩展: 让仓库侧 embedding 也能被中文需求命中
    cjk = _CJK_RE.findall(text)
    if cjk:
        text += " " + " ".join(_zh_aliases(cjk))
    return text


def embed_repo(repo: dict, dim: int = EMBED_DIM) -> list[float]:
    return embed_text(build_repo_text(repo), dim=dim)


# ============================================================
# API 嵌入 (可选, 更高质量)
# ============================================================

def _api_embed(texts: list[str]) -> list[list[float]] | None:
    """调用 OpenAI 兼容 embedding API (可配置)。"""
    key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    url = os.environ.get("EMBEDDING_API_URL", "https://api.openai.com/v1/embeddings")
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        body = json.dumps({"model": model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = [d["embedding"] for d in data.get("data", [])]
        return out or None
    except Exception as e:
        print(f"[embedding] api error, fallback to local: {e}")
        return None


def embed_batch(repos: list[dict], dim: int = EMBED_DIM) -> list[list[float]]:
    """批量嵌入: 优先 API, 失败/无 key 回退本地。"""
    texts = [build_repo_text(r) for r in repos]
    api = _api_embed(texts)
    if api and len(api) == len(texts):
        return api
    return [embed_text(t, dim=dim) for t in texts]
