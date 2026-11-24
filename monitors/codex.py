#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex Agent Monitor Module
Detects local Codex configuration, CLI/desktop processes, session logs,
5-hour quota, weekly quota, remaining operations, and exact reset expiration time.
"""

import os
import re
import sqlite3
import subprocess
import time

def get_codex_status():
    status = {
        "name": "OpenAI Codex",
        "installed": False,
        "running": False,
        "pid": None,
        "app_version": "未知",
        "home_dir": os.path.expanduser("~/.codex"),
        "total_log_events": 0,
        "last_active": None,
        "five_hour_usage": {
            "events_5h": 0,
            "limit_events": 2500,
            "remaining_events": 2500,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": "随时可用",
            "reset_expire_time": "随时就绪",
            "human_used": "0 / 2500 操作"
        },
        "weekly_usage": {
            "events_week": 0,
            "limit_events": 15000,
            "remaining_events": 15000,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": "--",
            "reset_expire_time": "--",
            "human_used": "0 / 15000 操作"
        },
        "reset_stats": {
            "five_hour_remaining": 2500,
            "weekly_remaining": 15000,
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

    # 3. 读取 SQLite logs 计算 5小时、周额度、重置到期时间
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
            
            now_ts = int(time.time())
            
            # --- A. 5小时窗口 ---
            five_hours_ago = now_ts - (5 * 3600)
            cur.execute("SELECT count(*), min(ts) FROM logs WHERE ts >= ?;", (five_hours_ago,))
            fhr = cur.fetchone()
            
            ev_5h = 0
            limit_5h = 2500
            oldest_5h_ts = None
            if fhr:
                ev_5h = fhr[0] or 0
                oldest_5h_ts = fhr[1]
            
            rem_5h = max(0, limit_5h - ev_5h)
            pct_5h = round(min(100.0, (ev_5h / limit_5h) * 100), 1)
            
            reset_5h_str = "随时可用"
            reset_5h_expire = "随时就绪 (100% 额度可用)"
            if oldest_5h_ts and ev_5h > 0:
                sec_left_5h = max(0, int((oldest_5h_ts + 5 * 3600) - now_ts))
                rh = sec_left_5h // 3600
                rm = (sec_left_5h % 3600) // 60
                reset_5h_str = f"{rh}小时{rm:02d}分后释放" if rh > 0 else f"{rm}分钟后释放"
                expire_ts_5h = oldest_5h_ts + 5 * 3600
                reset_5h_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expire_ts_5h))

            status["five_hour_usage"] = {
                "events_5h": ev_5h,
                "limit_events": limit_5h,
                "remaining_events": rem_5h,
                "percent": pct_5h,
                "status": "critical" if pct_5h >= 90 else ("warning" if pct_5h >= 70 else "normal"),
                "reset_countdown_human": reset_5h_str,
                "reset_expire_time": reset_5h_expire,
                "human_used": f"{ev_5h} / {limit_5h} 操作"
            }

            # --- B. 周额度窗口 (7天) ---
            seven_days_ago = now_ts - (7 * 86400)
            cur.execute("SELECT count(*), min(ts) FROM logs WHERE ts >= ?;", (seven_days_ago,))
            wkr = cur.fetchone()
            
            ev_week = 0
            limit_week = 15000
            if wkr:
                ev_week = wkr[0] or 0

            rem_week = max(0, limit_week - ev_week)
            pct_week = round(min(100.0, (ev_week / limit_week) * 100), 1)

            # 计算周到期时间（自然周周一 00:00）
            utc_now = time.gmtime(now_ts)
            days_to_monday = (7 - utc_now.tm_wday) % 7
            if days_to_monday == 0 and (utc_now.tm_hour > 0 or utc_now.tm_min > 0):
                days_to_monday = 7
            next_reset_epoch = now_ts + (days_to_monday * 86400) - (utc_now.tm_hour * 3600 + utc_now.tm_min * 60 + utc_now.tm_sec)
            sec_left_wk = max(0, int(next_reset_epoch - now_ts))
            left_days = sec_left_wk // 86400
            left_hours = (sec_left_wk % 86400) // 3600
            weekly_reset_str = f"{left_days}天{left_hours}小时后重置"
            weekly_expire_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(next_reset_epoch))

            status["weekly_usage"] = {
                "events_week": ev_week,
                "limit_events": limit_week,
                "remaining_events": rem_week,
                "percent": pct_week,
                "status": "critical" if pct_week >= 90 else ("warning" if pct_week >= 75 else "normal"),
                "reset_countdown_human": weekly_reset_str,
                "reset_expire_time": weekly_expire_time,
                "human_used": f"{ev_week} / {limit_week} 操作"
            }

            status["reset_stats"] = {
                "five_hour_remaining": rem_5h,
                "weekly_remaining": rem_week,
                "cycle_status": "充足" if rem_5h > 500 else "紧张"
            }
        except Exception as e:
            status["details"]["db_err"] = str(e)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return status

if __name__ == "__main__":
    import json
    print(json.dumps(get_codex_status(), indent=2, ensure_ascii=False))
