#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex Agent Monitor Module
Detects local Codex configuration, CLI/desktop processes, session logs,
5-hour quota, weekly quota, remaining operations, and exact reset expiration time.
"""

import glob
import json
import os
import re
import sqlite3
import subprocess
import threading
import time

# Cache latest rate_limits by (fpath, mtime, size)
_CODEX_RL_CACHE = {"key": None, "data": None}
_CODEX_CACHE_LOCK = threading.Lock()

def _load_official_codex_rate_limits(codex_home):
    """Read official 5h/7d rate_limits from the most recent Codex session JSONL."""
    sess_root = os.path.join(codex_home, "sessions")
    if not os.path.isdir(sess_root):
        return None
    try:
        sess_files = glob.glob(os.path.join(sess_root, "**", "*.jsonl"), recursive=True)
        if not sess_files:
            return None
        # Sort by mtime descending and inspect only the newest few files
        sess_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except Exception:
        return None

    top_files = sess_files[:8]
    try:
        cache_key = tuple((p, os.path.getmtime(p), os.path.getsize(p)) for p in top_files)
    except Exception:
        cache_key = None

    with _CODEX_CACHE_LOCK:
        if cache_key and _CODEX_RL_CACHE["key"] == cache_key:
            return _CODEX_RL_CACHE["data"]

    latest_rl = None
    latest_ts_str = ""
    for sf in top_files:
        try:
            with open(sf, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                        payload = obj.get("payload") or {}
                        rl = payload.get("rate_limits")
                        if isinstance(rl, dict) and (rl.get("primary") or rl.get("secondary")):
                            ts_str = str(obj.get("timestamp") or "")
                            if ts_str >= latest_ts_str:
                                latest_ts_str = ts_str
                                latest_rl = {"timestamp": ts_str, "rate_limits": rl}
                    except Exception:
                        pass
        except Exception:
            pass
        if latest_rl:
            break

    with _CODEX_CACHE_LOCK:
        _CODEX_RL_CACHE["key"] = cache_key
        _CODEX_RL_CACHE["data"] = latest_rl
    return latest_rl

def _format_countdown(sec_left):
    if sec_left <= 0:
        return "随时可用"
    days = sec_left // 86400
    hours = (sec_left % 86400) // 3600
    mins = (sec_left % 3600) // 60
    if days > 0:
        return f"{days}天{hours}小时后重置"
    if hours > 0:
        return f"{hours}小时{mins:02d}分后重置"
    return f"{mins}分钟后重置"

def get_codex_status():
    status = {
        "name": "OpenAI Codex",
        "installed": False,
        "running": False,
        "pid": None,
        "app_version": "未知",
        "plan_type": "未知",
        "data_source": "本地日志估算",
        "home_dir": os.path.expanduser("~/.codex"),
        "total_log_events": 0,
        "last_active": None,
        "five_hour_usage": {
            "events_5h": 0,
            "limit_events": 2500,
            "remaining_events": 2500,
            "remaining_percent": 100.0,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": "随时可用",
            "reset_expire_time": "随时就绪",
            "human_used": "0.0% / 100%"
        },
        "weekly_usage": {
            "events_week": 0,
            "limit_events": 15000,
            "remaining_events": 15000,
            "remaining_percent": 100.0,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": "--",
            "reset_expire_time": "--",
            "human_used": "0.0% / 100%"
        },
        "reset_stats": {
            "five_hour_remaining": "100.0%",
            "weekly_remaining": "100.0%",
            "cycle_status": "正常循环"
        },
        "details": {}
    }

    codex_home = status["home_dir"]
    if os.path.isdir(codex_home):
        status["installed"] = True
    else:
        return status

    # 1. 检查运行进程
    try:
        ps_output = subprocess.check_output(["ps", "-axo", "pid,command"], text=True, stderr=subprocess.DEVNULL)
        for line in ps_output.splitlines():
            line_strip = line.strip()
            if "grep" in line_strip:
                continue
            if "codex" in line_strip.lower() and any(k in line_strip.lower() for k in ["bin/codex", "codex-cli", "codex.app", "codex helper"]):
                parts = line_strip.split(None, 1)
                if parts:
                    status["running"] = True
                    status["pid"] = int(parts[0])
                    break
    except Exception as e:
        status["details"]["process_err"] = str(e)

    # 2. 从 config.toml 读取版本
    config_path = os.path.join(codex_home, "config.toml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                ver_match = re.search(r'BROWSER_USE_CODEX_APP_VERSION\s*=\s*"([^"]+)"', content)
                if ver_match:
                    status["app_version"] = ver_match.group(1)
        except Exception as e:
            status["details"]["config_err"] = str(e)

    # 3. 读取 SQLite logs 获取总日志数与最近活跃时间
    logs_db = os.path.join(codex_home, "logs_2.sqlite")
    if os.path.exists(logs_db):
        conn = None
        try:
            conn = sqlite3.connect(f"file:{logs_db}?mode=ro", uri=True, timeout=2.0)
            cur = conn.cursor()

            cur.execute("SELECT count(*) FROM logs;")
            row = cur.fetchone()
            if row:
                status["total_log_events"] = row[0]

            cur.execute("SELECT ts FROM logs ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
            if row and row[0]:
                ts = row[0]
                status["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except Exception as e:
            status["details"]["db_err"] = str(e)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    # 4. 优先从 ~/.codex/sessions/*.jsonl 读取官方真实 rate_limits (5h + 7d)
    now_ts = int(time.time())
    rl_wrap = _load_official_codex_rate_limits(codex_home)
    if rl_wrap and rl_wrap.get("rate_limits"):
        rl = rl_wrap["rate_limits"]
        status["data_source"] = "官方 Session 真实配额"
        if rl.get("plan_type"):
            status["plan_type"] = str(rl.get("plan_type")).capitalize()

        primary = rl.get("primary") or {}
        p_resets = int(primary.get("resets_at") or 0)
        p_used = float(primary.get("used_percent") or 0.0)
        if p_resets > 0 and now_ts >= p_resets:
            # 窗口已到期重置
            p_used = 0.0
            p_rem = 100.0
            p_countdown = "已重置 (100% 可用)"
            p_expire = "随时就绪"
        else:
            p_used = round(min(100.0, max(0.0, p_used)), 1)
            p_rem = round(max(0.0, 100.0 - p_used), 1)
            p_countdown = _format_countdown(max(0, p_resets - now_ts)) if p_resets > 0 else "5小时滑动窗口"
            p_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p_resets)) if p_resets > 0 else "随时就绪"

        status["five_hour_usage"] = {
            "events_5h": 0,
            "limit_events": 100,
            "remaining_events": int(round(p_rem)),
            "remaining_percent": p_rem,
            "percent": p_used,
            "status": "critical" if p_used >= 90 else ("warning" if p_used >= 70 else "normal"),
            "reset_countdown_human": p_countdown,
            "reset_expire_time": p_expire,
            "human_used": f"已用 {p_used}% (剩余 {p_rem}%)"
        }

        secondary = rl.get("secondary") or {}
        s_resets = int(secondary.get("resets_at") or 0)
        s_used = float(secondary.get("used_percent") or 0.0)
        if s_resets > 0 and now_ts >= s_resets:
            s_used = 0.0
            s_rem = 100.0
            s_countdown = "已重置 (100% 可用)"
            s_expire = "随时就绪"
        else:
            s_used = round(min(100.0, max(0.0, s_used)), 1)
            s_rem = round(max(0.0, 100.0 - s_used), 1)
            s_countdown = _format_countdown(max(0, s_resets - now_ts)) if s_resets > 0 else "7天周窗口"
            s_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s_resets)) if s_resets > 0 else "--"

        status["weekly_usage"] = {
            "events_week": 0,
            "limit_events": 100,
            "remaining_events": int(round(s_rem)),
            "remaining_percent": s_rem,
            "percent": s_used,
            "status": "critical" if s_used >= 90 else ("warning" if s_used >= 75 else "normal"),
            "reset_countdown_human": s_countdown,
            "reset_expire_time": s_expire,
            "human_used": f"已用 {s_used}% (剩余 {s_rem}%)"
        }

        status["reset_stats"] = {
            "five_hour_remaining": f"{p_rem}%",
            "weekly_remaining": f"{s_rem}%",
            "cycle_status": "充足" if p_rem > 30 else ("警示" if p_rem > 10 else "紧张")
        }

    return status

if __name__ == "__main__":
    import json
    print(json.dumps(get_codex_status(), indent=2, ensure_ascii=False))
