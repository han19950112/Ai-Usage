#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex Agent Monitor Module
Detects local Codex configuration, CLI/desktop processes, session logs, and activity.
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
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": "随时可用",
            "human_used": "0 / 2500 次"
        },
        "details": {}
    }

    codex_home = status["home_dir"]
    if os.path.isdir(codex_home):
        status["installed"] = True
    else:
        return status

    # 1. Check running processes
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

    # 2. Parse config.toml for version and settings
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

    # 3. Read SQLite logs for event count and last active timestamp
    logs_db = os.path.join(codex_home, "logs_2.sqlite")
    if os.path.exists(logs_db):
        try:
            conn = sqlite3.connect(f"file:{logs_db}?mode=ro", uri=True)
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
            
            # 5-hour rolling usage query
            now_ts = int(time.time())
            five_hours_ago = now_ts - (5 * 3600)
            cur.execute("SELECT count(*), min(ts) FROM logs WHERE ts >= ?;", (five_hours_ago,))
            fhr = cur.fetchone()
            if fhr:
                ev_5h = fhr[0] or 0
                oldest_ts = fhr[1]
                limit_ev = 2500
                ev_pct = round(min(100.0, (ev_5h / limit_ev) * 100), 1)
                
                reset_str = "随时可用"
                if oldest_ts and ev_5h > 0:
                    sec_left = max(0, int((oldest_ts + 5 * 3600) - now_ts))
                    rh = sec_left // 3600
                    rm = (sec_left % 3600) // 60
                    reset_str = f"{rh}小时{rm:02d}分后开始释放" if rh > 0 else f"{rm}分钟后开始释放"

                status["five_hour_usage"] = {
                    "events_5h": ev_5h,
                    "limit_events": limit_ev,
                    "percent": ev_pct,
                    "status": "critical" if ev_pct >= 90 else ("warning" if ev_pct >= 70 else "normal"),
                    "reset_countdown_human": reset_str,
                    "human_used": f"{ev_5h} / {limit_ev} 操作"
                }

            conn.close()
        except Exception as e:
            status["details"]["db_err"] = str(e)

    return status

if __name__ == "__main__":
    import json
    print(json.dumps(get_codex_status(), indent=2, ensure_ascii=False))
