"""GitHub API 客户端 —— 泛化自 wvb-cc-radar 的 gh_request 重试模型。

原实现要点 (wvb-cc-radar/scripts/fetch.py):
  - 重试调度: 5s / 15s 两次退避 (单请求最多 3 次尝试, 总延迟 ≤20s)
  - 可重试: 403 (rate limit) / 429 / 5xx
  - 不重试: 404 / 422 (永久性错误)
  - 每次请求后读取 X-RateLimit-Remaining 供调度/健康检查

本模块保持相同的重试与请求语义，并增加:
  - 显式返回剩余配额 (供上层日志与节流)
  - direct /repos 404 时返回 None (allowlist 中已删仓库静默跳过)
  - 匿名模式 (无 GITHUB_TOKEN) 下 sleep 拉长以适配 60 req/hr
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote_plus

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = Path("/run/secrets/github_token").read_text().strip() if Path(
    "/run/secrets/github_token"
).exists() else ""
GITHUB_TOKEN = GITHUB_TOKEN or __import__("os").environ.get("GITHUB_TOKEN", "").strip()

# 重试退避 (秒) —— 与 wvb-cc-radar 一致
GH_RETRY_BACKOFFS = [5, 15]

# 匿名模式 (60 req/hr) 下请求间隔; 认证模式 (5000 req/hr) 下 2s
SLEEP_ANON = 7
SLEEP_AUTH = 2


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "huoqujiazhixinxi-reserve/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def gh_request(url: str) -> tuple[dict, dict]:
    """GET 请求 GitHub API，带 5s/15s 退避重试。返回 (json, headers)。"""
    req = urllib.request.Request(url, headers=_headers())
    attempts = len(GH_RETRY_BACKOFFS) + 1
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, dict(resp.headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            retryable = e.code == 403 or e.code == 429 or e.code >= 500
            if not retryable or attempt > len(GH_RETRY_BACKOFFS):
                print(f"[gh] HTTP {e.code}: {body[:300]}", file=__import__("sys").stderr)
                raise
            backoff = GH_RETRY_BACKOFFS[attempt - 1]
            print(
                f"[gh] HTTP {e.code} (attempt {attempt}/{attempts}), retrying in {backoff}s",
                file=__import__("sys").stderr,
            )
            time.sleep(backoff)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt > len(GH_RETRY_BACKOFFS):
                print(
                    f"[gh] request error (final attempt {attempt}/{attempts}): {e}",
                    file=__import__("sys").stderr,
                )
                raise
            backoff = GH_RETRY_BACKOFFS[attempt - 1]
            print(
                f"[gh] request error (attempt {attempt}/{attempts}), retrying in {backoff}s: {e}",
                file=__import__("sys").stderr,
            )
            time.sleep(backoff)
    raise RuntimeError("gh_request: exhausted retries without return or raise")


def search_repos(query: str, per_page: int) -> tuple[list[dict], dict]:
    """GitHub Search API 仓库检索 (按 stars 排序)。返回 (items, headers)。"""
    encoded = quote_plus(query)
    url = (
        f"{GITHUB_API}/search/repositories"
        f"?q={encoded}&sort=stars&order=desc&per_page={per_page}"
    )
    data, hdrs = gh_request(url)
    return data.get("items", []), hdrs


def get_readme(full_name: str, max_chars: int = 12000) -> str | None:
    """获取仓库 README 文本 (用于 LLM 功能索引/代码审核)。

    走 /repos/{owner}/{name}/readme (accept: application/vnd.github.raw) 直接拿原文,
    失败时回退 base64 JSON 解码。超长截断到 max_chars 以控制 LLM 输入。
    返回 None 表示无 README (空仓库/已删)。
    """
    url = f"{GITHUB_API}/repos/{full_name}/readme"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # raw 端点直接返回文本; 若拿到的是 JSON (老接口兜底) 则解码 content
            if raw.lstrip().startswith("{"):
                try:
                    data = json.loads(raw)
                    import base64
                    raw = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
                except Exception:
                    pass
            return raw[:max_chars] if raw else None
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            print(f"[gh] readme not found {full_name} (HTTP {e.code})", file=__import__("sys").stderr)
            return None
        print(f"[gh] readme error {full_name}: HTTP {e.code}", file=__import__("sys").stderr)
        return None
    except Exception as e:
        print(f"[gh] readme error {full_name}: {e}", file=__import__("sys").stderr)
        return None


def get_repo_direct(full_name: str) -> tuple[dict | None, dict]:
    """/repos/{owner}/{name} 直连。404 返回 (None, {}) 以便 allowlist 静默跳过。"""
    url = f"{GITHUB_API}/repos/{full_name}"
    try:
        data, hdrs = gh_request(url)
        return data, hdrs
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[gh] direct 404 {full_name}", file=__import__("sys").stderr)
            return None, {}
        raise


def sleep_between(auth: bool) -> None:
    time.sleep(SLEEP_AUTH if auth else SLEEP_ANON)
