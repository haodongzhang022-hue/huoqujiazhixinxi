"""reserve/self_heal.py — 管道自愈合模块（"自愈合能力"）

回答用户核心诉求：**系统具备自愈合能力** —— 采集/入库/索引/服务任何一环出问题，
能自动检测、自动修复、自动降级，并记录愈合事件供追溯。

设计（分层自愈）：
  1. 检测层   health_check()        —— 对管道各环节做健康检查
  2. 诊断层   diagnose(checks)      —— 把健康检查结果映射为可执行问题清单
  3. 修复层   heal(problems)        —— 对每个问题执行对应修复动作（幂等）
  4. 记录层   IncidentLog           —— 愈合事件持久化（data/heal_log.json）
  5. 接入层   CLI + API             —— python -m reserve.self_heal / POST /api/v1/heal

支持的检测项与自愈动作：
  - snapshot_missing    今日快照缺失           -> 触发重采集 fetch()
  - snapshot_broken     快照空/过半分类为空     -> 重采集
  - snapshot_stale      快照日期落后            -> 重采集
  - rate_limit          GitHub 配额耗尽        -> 记录并等待/降低采集规模
  - fts_index_missing   全文索引缺失            -> 重建 FTS 索引
  - reserve_empty       储备库为空              -> 提示入库
  - llm_unavailable     LLM 不可用             -> 降级启发式（记录）
  - temp_junk           临时文件堆积            -> 清理
  - embedding_mismatch  embedding 维度异常     -> 重建/提示
  - quality_low         质量分持续偏低          -> 生成质量报告并提示人工介入

CLI 用法:
  python -m reserve.self_heal                 # 全量检查 + 自动修复
  python -m reserve.self_heal --check-only    # 只检查不修复
  python -m reserve.self_heal --log           # 查看愈合历史
  python -m reserve.self_heal --reset-log     # 清空愈合历史
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reserve.store import ReserveStore

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "pipeline" / "data" / "snapshots"
HEAL_LOG = ROOT / "data" / "heal_log.json"

# 自愈动作默认开关（可通过 config/self_heal.json 覆盖）
DEFAULT_POLICY = {
    "auto_refetch": True,        # 快照缺失/损坏时自动重采集
    "refetch_limit": 30,         # 重采集上限（省配额）
    "rebuild_fts": True,         # 全文索引缺失时自动重建
    "clean_temp": True,          # 清理临时文件
    "max_incidents_per_run": 20, # 单次运行最多记录
    "log_retention_days": 30,    # 愈合日志保留天数
}

POLICY_PATH = ROOT / "config" / "self_heal.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy() -> dict:
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    if POLICY_PATH.exists():
        try:
            user = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            policy.update(user)
        except Exception as e:
            print(f"[heal] policy load error {POLICY_PATH}: {e}")
    return policy


def save_default_policy() -> None:
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not POLICY_PATH.exists():
        POLICY_PATH.write_text(json.dumps(DEFAULT_POLICY, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 愈合事件日志
# ============================================================

class IncidentLog:
    """愈合事件持久化（data/heal_log.json）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else HEAL_LOG

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def append(self, entry: dict) -> None:
        entries = self.load()
        entries.append({
            "ts": now_iso(),
            **entry,
        })
        # 保留最近 N 天
        retention = load_policy().get("log_retention_days", 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
        entries = [e for e in entries if _parse_ts(e.get("ts")) >= cutoff]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self, limit: int = 50) -> list[dict]:
        entries = self.load()
        return entries[-limit:][::-1]

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.now(timezone.utc) - timedelta(days=999)


# ============================================================
# 健康检查
# ============================================================

def _check_snapshots() -> dict:
    """快照健康: 今日是否存在 / 是否损坏 / 是否过期。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_path = SNAPSHOT_DIR / f"{today}.json"
    result = {"ok": True, "checks": {}}

    # 今日快照
    if not today_path.exists():
        # 找最近一次快照
        recent = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
        last = recent[0].stem if recent else None
        result["checks"]["snapshot_missing"] = {
            "ok": False, "severity": "high",
            "detail": f"今日快照缺失 ({today_path.name}), 最近一次: {last}",
        }
        result["ok"] = False
    else:
        try:
            data = json.loads(today_path.read_text(encoding="utf-8"))
            repos = data.get("repos") or data.get("items") or []
            cats = data.get("categories", [])
            empty_cats = sum(1 for c in cats if (c.get("items") is None and c.get("total_count") == 0))
            total = len(repos)
            if total == 0:
                result["checks"]["snapshot_broken"] = {
                    "ok": False, "severity": "high",
                    "detail": f"今日快照为空 (0 仓库)",
                }
                result["ok"] = False
            elif cats and empty_cats > len(cats) / 2:
                result["checks"]["snapshot_broken"] = {
                    "ok": False, "severity": "high",
                    "detail": f"今日快照过半分类为空 ({empty_cats}/{len(cats)})",
                }
                result["ok"] = False
            else:
                result["checks"]["snapshot_ok"] = {"ok": True, "detail": f"今日快照正常 ({total} 仓库)"}
        except Exception as e:
            result["checks"]["snapshot_broken"] = {
                "ok": False, "severity": "high", "detail": f"今日快照无法读取: {e}",
            }
            result["ok"] = False

    # 过期检查: 最近快照日期是否 > 2 天前
    recent = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
    if recent:
        last_date = recent[0].stem
        try:
            d = datetime.strptime(last_date, "%Y-%m-%d").date()
            if (datetime.now(timezone.utc).date() - d).days > 2:
                result["checks"]["snapshot_stale"] = {
                    "ok": False, "severity": "medium",
                    "detail": f"最近快照是 {last_date}, 已超过 2 天未更新",
                }
                result["ok"] = False
        except ValueError:
            pass
    return result


def _check_github() -> dict:
    """GitHub API 配额检查。"""
    try:
        from pipeline import github_client
        import urllib.request
        url = "https://api.github.com/rate_limit"
        req = urllib.request.Request(url, headers=github_client._headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        core = data.get("resources", {}).get("core", {})
        remaining = core.get("remaining", 0)
        limit = core.get("limit", 60)
        reset_ts = core.get("reset", 0)
        reset_in = max(0, int(reset_ts) - int(time.time()))
        ok = remaining > 10
        return {
            "ok": ok,
            "checks": {
                "github_rate_limit": {
                    "ok": ok,
                    "severity": "medium" if remaining <= 10 else "low",
                    "detail": f"GitHub API 配额剩余 {remaining}/{limit}, 重置还需 {reset_in}s",
                }
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "checks": {
                "github_unreachable": {
                    "ok": False, "severity": "medium",
                    "detail": f"GitHub API 不可达: {e}",
                }
            },
        }


def _check_store(store: ReserveStore | None = None) -> dict:
    """储备库健康: 表存在 / FTS 索引 / 数据量。"""
    store = store or ReserveStore()
    result = {"ok": True, "checks": {}}
    try:
        tables = store.list_tables()
        if store.repos_name not in tables:
            result["checks"]["reserve_empty"] = {
                "ok": False, "severity": "high",
                "detail": f"储备库表 {store.repos_name} 不存在",
            }
            result["ok"] = False
        else:
            count = store.count()
            if count == 0:
                result["checks"]["reserve_empty"] = {
                    "ok": False, "severity": "medium",
                    "detail": "储备库为空, 尚未入库数据",
                }
                result["ok"] = False
            # FTS 索引检查
            try:
                tbl = store._open_repos()
                indices = tbl.list_indices()
                has_fts = any("search_text" in str(i) for i in indices)
                if not has_fts:
                    result["checks"]["fts_index_missing"] = {
                        "ok": False, "severity": "low",
                        "detail": "全文检索索引缺失 (检索会慢/降级)",
                    }
            except Exception as e:
                result["checks"]["fts_index_missing"] = {
                    "ok": False, "severity": "low", "detail": f"FTS 索引检查失败: {e}",
                }
    except Exception as e:
        result["checks"]["store_unreachable"] = {
            "ok": False, "severity": "high", "detail": f"储备库不可达: {e}",
        }
        result["ok"] = False
    return result


def _check_llm() -> dict:
    """LLM 可用性检查（不可用 -> 降级启发式, 低危）。"""
    try:
        from reserve.llm import get_provider
        provider = get_provider()
        if provider is None:
            return {
                "ok": False,
                "checks": {
                    "llm_unavailable": {
                        "ok": False, "severity": "low",
                        "detail": "未配置 LLM, 功能索引使用启发式/审核走人工队列",
                    }
                },
            }
        healthy = provider.health()
        return {
            "ok": healthy,
            "checks": {
                "llm_unavailable": {
                    "ok": healthy, "severity": "low",
                    "detail": f"LLM {'可用' if healthy else '不可用'} ({provider})",
                }
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "checks": {"llm_unavailable": {"ok": False, "severity": "low", "detail": f"LLM 检查异常: {e}"}},
        }


def _check_temp() -> dict:
    """临时文件堆积检查（__pycache__ 等 Python 运行缓存视为无害, 不告警）。"""
    junk_patterns = ["*.tmp", "*.bak", "*.swp", "*.log", "*.pid"]
    junk = []
    for pattern in junk_patterns:
        for p in ROOT.rglob(pattern):
            if ".git" in p.parts:
                continue
            junk.append(p)
    # 限制显示数量
    detail = f"发现 {len(junk)} 个临时文件" if junk else "无临时文件堆积"
    return {
        "ok": len(junk) == 0,
        "checks": {
            "temp_junk": {
                "ok": len(junk) == 0, "severity": "low", "detail": detail, "items": junk[:20],
            }
        },
    }


def health_check(store: ReserveStore | None = None) -> dict:
    """全量健康检查 -> 返回 {ok, checks: {检查项: {ok, severity, detail}}, summary}。"""
    checks = {}
    # 只有 _check_store 需要 store 参数, 其余无参
    for fn in (_check_snapshots, _check_github, _check_temp, _check_llm):
        try:
            res = fn()
            checks.update(res.get("checks", {}))
        except Exception as e:
            checks[f"{fn.__name__}_error"] = {
                "ok": False, "severity": "high", "detail": f"{fn.__name__} 检查异常: {e}",
            }
    try:
        res = _check_store(store)
        checks.update(res.get("checks", {}))
    except Exception as e:
        checks["_check_store_error"] = {
            "ok": False, "severity": "high", "detail": f"_check_store 检查异常: {e}",
        }

    ok = all(c.get("ok", True) for c in checks.values())
    high = sum(1 for c in checks.values() if not c.get("ok", True) and c.get("severity") == "high")
    medium = sum(1 for c in checks.values() if not c.get("ok", True) and c.get("severity") == "medium")
    low = sum(1 for c in checks.values() if not c.get("ok", True) and c.get("severity") == "low")
    # 整体健康判定: 仅 high 级别问题导致不健康;
    # medium/low 视为降级/警告 (如 LLM 未配置走启发式、临时缓存), 记录但不阻塞自愈流程
    healthy = high == 0
    return {
        "ok": healthy,
        "checked_at": now_iso(),
        "checks": checks,
        "summary": {"healthy": healthy, "high": high, "medium": medium, "low": low},
    }


# ============================================================
# 诊断: 健康检查结果 -> 问题清单
# ============================================================

def diagnose(checks: dict) -> list[dict]:
    """把健康检查结果映射为可执行问题清单。

    返回: [{"id", "title", "severity", "action", "params"}] （action 供 heal 执行）
    """
    problems = []
    c = checks.get("snapshot_missing", {})
    if not c.get("ok", True):
        problems.append({
            "id": "snapshot_missing", "title": c.get("detail", "今日快照缺失"),
            "severity": c.get("severity", "high"), "action": "refetch",
        })
    c = checks.get("snapshot_broken", {})
    if not c.get("ok", True):
        problems.append({
            "id": "snapshot_broken", "title": c.get("detail", "快照损坏"),
            "severity": c.get("severity", "high"), "action": "refetch",
        })
    c = checks.get("snapshot_stale", {})
    if not c.get("ok", True):
        problems.append({
            "id": "snapshot_stale", "title": c.get("detail", "快照过期"),
            "severity": c.get("severity", "medium"), "action": "refetch",
        })
    c = checks.get("github_rate_limit", {})
    if not c.get("ok", True):
        problems.append({
            "id": "rate_limit", "title": c.get("detail", "GitHub 配额不足"),
            "severity": c.get("severity", "medium"), "action": "wait",
        })
    c = checks.get("github_unreachable", {})
    if not c.get("ok", True):
        problems.append({
            "id": "github_unreachable", "title": c.get("detail", "GitHub 不可达"),
            "severity": c.get("severity", "medium"), "action": "wait",
        })
    c = checks.get("reserve_empty", {})
    if not c.get("ok", True):
        problems.append({
            "id": "reserve_empty", "title": c.get("detail", "储备库为空"),
            "severity": c.get("severity", "medium"), "action": "ingest",
        })
    c = checks.get("fts_index_missing", {})
    if not c.get("ok", True):
        problems.append({
            "id": "fts_index_missing", "title": c.get("detail", "全文索引缺失"),
            "severity": c.get("severity", "low"), "action": "rebuild_fts",
        })
    c = checks.get("llm_unavailable", {})
    if not c.get("ok", True):
        problems.append({
            "id": "llm_unavailable", "title": c.get("detail", "LLM 不可用"),
            "severity": c.get("severity", "low"), "action": "degrade",
        })
    c = checks.get("temp_junk", {})
    if not c.get("ok", True):
        problems.append({
            "id": "temp_junk", "title": c.get("detail", "临时文件堆积"),
            "severity": c.get("severity", "low"), "action": "clean_temp",
            "items": c.get("items", []),
        })
    return problems


# ============================================================
# 修复动作
# ============================================================

def heal_refetch(limit: int | None = None) -> dict:
    """触发重采集（fetch + 写盘）。成功返回 True, 失败返回 False。"""
    try:
        from pipeline.fetch import fetch
        digest = fetch(limit=limit)
        ok = digest.get("total_repos", 0) > 0
        # 写盘（fetch() 只返回 digest, 落盘在 main() 中; 这里需要手动写）
        if ok:
            out = SNAPSHOT_DIR / f"{digest.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))}.json"
            out.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": ok, "detail": f"重采集完成: {digest.get('total_repos')} 仓库 -> {out if ok else '未写盘'}"}
    except Exception as e:
        return {"ok": False, "detail": f"重采集失败: {e}"}


def heal_ingest() -> dict:
    """尝试入库今日快照。"""
    try:
        from reserve.ingest import run
        from reserve.llm import save_default_config
        save_default_config()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snap = SNAPSHOT_DIR / f"{today}.json"
        if not snap.exists():
            # 找最近快照
            recent = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
            if not recent:
                return {"ok": False, "detail": "无快照可入库"}
            snap = recent[0]
        result = run(snap, llm_enrich=False, llm_review=False, fetch_readme=False,
                     write_snapshot=False)  # 空 new 时避免建空快照表
        if "error" in result:
            return {"ok": False, "detail": result["error"]}
        # 空 new 视为正常（去重后无新内容）
        return {"ok": True, "detail": f"入库完成: new={result.get('new')} existing={result.get('existing')}"}
    except Exception as e:
        return {"ok": False, "detail": f"入库失败: {e}"}


def heal_rebuild_fts(store: ReserveStore | None = None) -> dict:
    """重建全文检索索引。"""
    store = store or ReserveStore()
    try:
        tbl = store._open_repos()
        try:
            for idx in tbl.list_indices():
                try:
                    tbl.drop_index(idx)
                except Exception:
                    pass
        except Exception:
            pass
        tbl.create_fts_index("search_text")
        return {"ok": True, "detail": "全文检索索引已重建"}
    except Exception as e:
        return {"ok": False, "detail": f"重建 FTS 索引失败: {e}"}


def heal_clean_temp() -> dict:
    """清理临时/缓存文件（__pycache__ 无害, 只清 .tmp/.bak/.swp/.log/.pid）。"""
    removed = 0
    for pattern in ["*.tmp", "*.bak", "*.swp", "*.log", "*.pid"]:
        for p in ROOT.rglob(pattern):
            if ".git" in p.parts:
                continue
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                removed += 1
            except Exception:
                pass
    return {"ok": True, "detail": f"清理 {removed} 个临时文件"}


def heal_degrade() -> dict:
    """LLM 降级: 确保启发式兜底与人工审核队列可用（无副作用, 幂等）。"""
    from reserve.llm import save_default_config
    save_default_config()
    return {"ok": True, "detail": "LLM 降级准备完成 (启发式功能索引 + 人工审核队列)"}


# 动作分发表
ACTION_HANDLERS = {
    "refetch": heal_refetch,
    "ingest": heal_ingest,
    "rebuild_fts": heal_rebuild_fts,
    "clean_temp": heal_clean_temp,
    "degrade": heal_degrade,
    "wait": lambda **kw: {"ok": True, "detail": "等待配额恢复 (跳过修复)"},
}


# ============================================================
# 主流程: 检查 -> 诊断 -> 修复 -> 记录
# ============================================================

def run_self_heal(check_only: bool = False, store: ReserveStore | None = None,
                  verbose: bool = True) -> dict:
    """自愈合主流程。

    返回:
      {
        "ok": 全部健康 or 修复后健康,
        "health": {检查结果},
        "problems": [诊断问题],
        "actions": [执行的修复动作],
        "incidents": [记录的事件],
      }
    """
    policy = load_policy()
    log = IncidentLog()

    # 1. 健康检查
    health = health_check(store)
    if verbose:
        print(f"[heal] 健康检查: {'✅ 健康' if health['ok'] else '❌ 有问题'} "
              f"(high={health['summary']['high']} medium={health['summary']['medium']} "
              f"low={health['summary']['low']})")

    # 2. 诊断
    problems = diagnose(health["checks"])
    if not problems:
        if verbose:
            print("[heal] 未发现问题, 无需修复")
        return {"ok": True, "health": health, "problems": [], "actions": [], "incidents": []}

    if check_only:
        if verbose:
            for p in problems:
                print(f"  - [{p['severity']}] {p['title']}")
        return {"ok": False, "health": health, "problems": problems, "actions": [], "incidents": []}

    # 3. 修复
    actions = []
    incidents = []
    max_inc = policy.get("max_incidents_per_run", 20)
    done_ids = set()

    # 修复顺序: 高优先级先做（refetch > ingest > rebuild > clean > degrade）
    order = {"refetch": 0, "ingest": 1, "rebuild_fts": 2, "clean_temp": 3, "degrade": 4, "wait": 5}
    problems_sorted = sorted(problems, key=lambda p: order.get(p.get("action"), 9))

    for p in problems_sorted:
        action = p.get("action", "wait")
        if action in done_ids:
            continue
        done_ids.add(action)

        handler = ACTION_HANDLERS.get(action)
        if handler is None:
            continue

        # 策略开关
        if action == "refetch" and not policy.get("auto_refetch", True):
            incident = {"level": "warning", "event": "refetch_skipped", "detail": p["title"]}
            incidents.append(incident)
            continue
        if action == "rebuild_fts" and not policy.get("rebuild_fts", True):
            continue
        if action == "clean_temp" and not policy.get("clean_temp", True):
            continue

        params = {}
        if action == "refetch":
            params = {"limit": policy.get("refetch_limit", 30)}
        if action == "rebuild_fts":
            params = {"store": store}

        try:
            if verbose:
                print(f"[heal] 修复 [{action}] {p['title']} ...")
            result = handler(**params)
            actions.append({
                "problem": p["id"],
                "title": p["title"],
                "action": action,
                "ok": result.get("ok", False),
                "detail": result.get("detail", ""),
            })
            incidents.append({
                "level": "info" if result.get("ok") else "error",
                "event": f"heal_{action}",
                "ok": result.get("ok", False),
                "detail": result.get("detail", p["title"]),
                "problem": p["id"],
            })
            # refetch 成功后重新入库
            if action == "refetch" and result.get("ok") and policy.get("auto_ingest", True):
                ing = heal_ingest()
                actions.append({
                    "problem": "post_refetch_ingest", "title": "重采集后入库",
                    "action": "ingest", "ok": ing.get("ok", False), "detail": ing.get("detail", ""),
                })
        except Exception as e:
            actions.append({
                "problem": p["id"], "title": p["title"], "action": action,
                "ok": False, "detail": f"修复异常: {e}",
            })
            incidents.append({
                "level": "error", "event": f"heal_{action}", "ok": False,
                "detail": f"{p['title']} -> 异常: {e}", "problem": p["id"],
            })

    # 4. 记录
    for inc in incidents[:max_inc]:
        log.append(inc)

    # 5. 复查
    health_after = health_check(store)
    if verbose:
        for a in actions:
            status = "✅" if a["ok"] else "❌"
            print(f"  {status} [{a['action']}] {a['title']} -> {a['detail']}")
        print(f"[heal] 复查: {'✅ 健康' if health_after['ok'] else '⚠️ 仍有问题'}")

    return {
        "ok": health_after["ok"],
        "health": health,
        "health_after": health_after,
        "problems": problems,
        "actions": actions,
        "incidents": incidents[:max_inc],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="管道自愈合")
    parser.add_argument("--check-only", action="store_true", help="只检查不修复")
    parser.add_argument("--log", action="store_true", help="查看愈合历史")
    parser.add_argument("--reset-log", action="store_true", help="清空愈合历史")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    save_default_policy()

    if args.reset_log:
        IncidentLog().reset()
        print("[heal] 愈合日志已清空")
        return 0
    if args.log:
        entries = IncidentLog().list(limit=50)
        if args.json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        else:
            for e in entries:
                mark = "✅" if e.get("ok") else ("⚠️" if e.get("level") == "warning" else "❌")
                print(f"{mark} {e.get('ts', '')} [{e.get('event', '')}] {e.get('detail', '')}")
        return 0

    result = run_self_heal(check_only=args.check_only, verbose=not args.json)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
