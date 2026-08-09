"""reserve/llm.py — LLM Provider 抽象层（零第三方依赖, 标准库 urllib 实现）

解决用户核心诉求：**功能索引 / 代码审核 / 读项目发布者介绍都需要大模型**，
并**允许自定义接入用户的 API 服务或本地大模型**。

支持三类接入（按优先级自动探测）:

  1. OpenAI 兼容 API（任意自定义端点）:  LLM_BASE_URL + LLM_API_KEY + LLM_MODEL
     适用于 OpenAI / DeepSeek / Moonshot Kimi / 通义千问 / OneAPI 网关 /
     vLLM / LM Studio / Ollama 的 /v1 兼容端点 ... 只要实现
     `POST {base_url}/chat/completions` 即插即用。

  2. 本地 Ollama:  OLLAMA_BASE_URL（默认 http://localhost:11434）+ OLLAMA_MODEL
     走原生 `/api/chat`（支持 format=json）, 也可用其 OpenAI 兼容 `/v1` 端点。

  3. 无任何配置 -> get_provider() 返回 None, 调用方自动降级（启发式 / 人工审核）。

环境变量（LLM_* 全部可选）:

  LLM_PROVIDER        auto(默认) / openai / ollama / none
  LLM_BASE_URL        OpenAI 兼容端点, 如 https://api.openai.com/v1
  LLM_API_KEY         API key（本地 vLLM/Ollama 可留空）
  LLM_MODEL           模型名, 如 gpt-4o-mini / deepseek-chat / qwen2.5:7b
  OLLAMA_BASE_URL     本地 Ollama 地址, 默认 http://localhost:11434
  OLLAMA_MODEL        本地模型名, 默认 qwen2.5:7b
  LLM_TIMEOUT         请求超时秒数（默认 90）
  LLM_TEMPERATURE     采样温度（默认 0.2, 结构化任务偏低）

用法:

  from reserve.llm import get_provider, complete_json

  provider = get_provider()
  if provider is None:
      # 未配置 LLM -> 调用方用启发式/人工兜底
      ...
  out = provider.complete_json(system_prompt, user_prompt)
  # out: dict | None（解析失败/请求失败返回 None）
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "config", "llm.json")

# ============================================================
# 配置
# ============================================================

DEFAULT_CONFIG = {
    "provider": "auto",              # auto / openai / ollama / none
    "base_url": "",                  # OpenAI 兼容端点 (LLM_BASE_URL)
    "api_key": "",                   # LLM_API_KEY
    "model": "",                     # LLM_MODEL
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "qwen2.5:7b",
    "timeout": 90,
    "temperature": 0.2,
    "enrich_enabled": True,          # 入库时是否启用 LLM 功能索引增强
    "review_enabled": True,          # 是否启用 LLM 代码审核 (action 候选)
}


def _load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if v is not None and v != ""})
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[llm] config load error {CONFIG_PATH}: {e}")
    return cfg


def load_config() -> dict:
    """读取 LLM 配置（config/llm.json + 环境变量覆盖, 环境变量优先）。"""
    cfg = _load_config()
    # 环境变量覆盖
    env_map = {
        "LLM_PROVIDER": "provider",
        "LLM_BASE_URL": "base_url",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
        "OLLAMA_BASE_URL": "ollama_base_url",
        "OLLAMA_MODEL": "ollama_model",
        "LLM_TIMEOUT": "timeout",
        "LLM_TEMPERATURE": "temperature",
    }
    for env, key in env_map.items():
        val = os.environ.get(env, "").strip()
        if val:
            if key == "timeout":
                try:
                    cfg[key] = int(val)
                except ValueError:
                    pass
            elif key == "temperature":
                try:
                    cfg[key] = float(val)
                except ValueError:
                    pass
            else:
                cfg[key] = val
    # 兼容旧变量: EMBEDDING_API_KEY / OPENAI_API_KEY 也可作为 LLM key 兜底
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("EMBEDDING_API_KEY", "").strip() or \
                         os.environ.get("OPENAI_API_KEY", "").strip()
    if not cfg.get("base_url") and cfg.get("api_key"):
        cfg["base_url"] = "https://api.openai.com/v1"
    if not cfg.get("model") and cfg.get("base_url"):
        cfg["model"] = "gpt-4o-mini"
    return cfg


def save_default_config() -> None:
    """写入默认 config/llm.json（仅当不存在）。"""
    path = os.path.dirname(CONFIG_PATH)
    os.makedirs(path, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"[llm] wrote default config -> {CONFIG_PATH}")


# ============================================================
# Provider
# ============================================================

@dataclass
class LLMProvider:
    """统一 LLM 调用封装（OpenAI 兼容 / Ollama 原生）。"""

    provider: str = "openai"          # openai / ollama
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 90
    temperature: float = 0.2

    # ---------- 基础请求 ----------

    def _openai_chat(self, messages: list[dict], json_mode: bool = True) -> dict | None:
        """OpenAI 兼容 /chat/completions。"""
        url = self.base_url.rstrip("/") + "/chat/completions"
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return self._post(url, body, headers)

    def _ollama_chat(self, messages: list[dict], json_mode: bool = True) -> dict | None:
        """Ollama 原生 /api/chat（format=json 兼容结构化输出）。"""
        url = self.ollama_url().rstrip("/") + "/api/chat"
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if json_mode:
            body["format"] = "json"
        headers = {"Content-Type": "application/json"}
        return self._post(url, body, headers)

    def ollama_url(self) -> str:
        cfg = load_config()
        return cfg.get("ollama_base_url", "http://localhost:11434")

    def _post(self, url: str, body: dict, headers: dict) -> dict | None:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            print(f"[llm] HTTP {e.code} from {url}: {detail}")
            return None
        except Exception as e:
            print(f"[llm] request error {url}: {e}")
            return None

    # ---------- 高层接口 ----------

    def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        """普通对话 -> 返回文本（失败返回 None）。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if self.provider == "ollama":
            resp = self._ollama_chat(messages, json_mode=json_mode)
            if resp is None:
                return None
            try:
                return resp["message"]["content"]
            except Exception:
                return None
        resp = self._openai_chat(messages, json_mode=json_mode)
        if resp is None:
            return None
        try:
            return resp["choices"][0]["message"]["content"]
        except Exception:
            return None

    def complete_json(self, system: str, user: str) -> dict | None:
        """结构化 JSON 输出 -> dict（失败/解析失败返回 None, 调用方降级）。"""
        text = self.chat(system, user, json_mode=True)
        if not text:
            return None
        return _parse_json(text)

    def health(self) -> bool:
        """健康检查: 发一条极短消息确认可用。"""
        try:
            out = self.chat("你是一个助手", "回复 ok", json_mode=False)
            return bool(out and out.strip())
        except Exception:
            return False

    def __repr__(self):
        return (f"LLMProvider({self.provider}, model={self.model!r}, "
                f"base_url={self.base_url!r})")


def _parse_json(text: str) -> dict | None:
    """宽容解析: 直接 JSON / 代码块包裹 / 截取首个 { }。"""
    text = text.strip()
    # 去掉 ```json ... ``` 代码块
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


# ============================================================
# 工厂
# ============================================================

def get_provider() -> LLMProvider | None:
    """按配置构建 provider；无可用配置返回 None（调用方降级）。"""
    cfg = load_config()
    provider_name = (cfg.get("provider") or "auto").lower()
    if provider_name == "none":
        return None

    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()

    # 显式 openai
    if provider_name == "openai":
        if not base_url and not model:
            return None
        return LLMProvider(provider="openai", base_url=base_url or "https://api.openai.com/v1",
                           api_key=api_key, model=model or "gpt-4o-mini",
                           timeout=int(cfg.get("timeout", 90)),
                           temperature=float(cfg.get("temperature", 0.2)))
    # 显式 ollama
    if provider_name == "ollama":
        return LLMProvider(provider="ollama", model=model or cfg.get("ollama_model", "qwen2.5:7b"),
                           timeout=int(cfg.get("timeout", 90)),
                           temperature=float(cfg.get("temperature", 0.2)))
    # auto: 有 OpenAI 兼容端点 -> openai; 否则尝试 ollama
    if base_url and model:
        return LLMProvider(provider="openai", base_url=base_url, api_key=api_key,
                           model=model, timeout=int(cfg.get("timeout", 90)),
                           temperature=float(cfg.get("temperature", 0.2)))
    # 尝试本地 Ollama (健康检查)
    try:
        ollama_url = (cfg.get("ollama_base_url") or "http://localhost:11434").rstrip("/")
        req = urllib.request.Request(ollama_url + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        if tags.get("models"):
            return LLMProvider(provider="ollama",
                               model=cfg.get("ollama_model", "qwen2.5:7b"),
                               timeout=int(cfg.get("timeout", 90)),
                               temperature=float(cfg.get("temperature", 0.2)))
    except Exception:
        pass
    return None


def complete_json(system: str, user: str) -> dict | None:
    """便捷函数: 用当前配置的 provider 做一次 JSON 输出（无 provider 返回 None）。"""
    p = get_provider()
    if p is None:
        return None
    return p.complete_json(system, user)


def describe_config() -> str:
    """返回当前 LLM 配置摘要（用于日志/文档, 不泄露 key）。"""
    cfg = load_config()
    p = get_provider()
    if p is None:
        return "未配置 LLM（功能索引将使用启发式, 代码审核需人工/@CodeBuddy）"
    key_hint = f"key={'已配置' if p.api_key else '无'}"
    return f"{p} | {key_hint}"


if __name__ == "__main__":
    import sys
    save_default_config()
    print("LLM 配置:", describe_config())
    if len(sys.argv) > 1:
        p = get_provider()
        if p is None:
            print("(无可用 provider, 输出为空)")
            sys.exit(0)
        out = p.complete_json("你是助手", sys.argv[1])
        print(json.dumps(out, ensure_ascii=False, indent=2) if out else "(无法解析 JSON 输出)")
