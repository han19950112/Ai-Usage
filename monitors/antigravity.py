#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Agent Monitor Module
Detects local Antigravity processes, language server status, IDE version,
active model, context window occupancy, and live token quotas.
"""

import calendar
import glob
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.error

def get_antigravity_status():
    status = {
        "name": "Google Antigravity",
        "running": False,
        "pid": None,
        "version": "未知",
        "language_server_running": False,
        "language_server_pid": None,
        "host_bridge_url": None,
        "bridge_online": False,
        "is_chinese_launcher": False,
        "active_conversations_count": 0,
        "last_active": None,
        "quota": {
            "current_model": "Gemini 3.8 Flash (High)",
            "context_window": {
                "used_tokens": 0,
                "max_tokens": 1000000,
                "percent": 0.0,
                "human": "0 / 1.0M"
            },
            "five_hour_usage": {
                "used_tokens": 0,
                "estimated_limit": 500000,
                "percent": 0.0,
                "status": "normal", # normal, warning, critical
                "reset_countdown_human": "滚动刷新中"
            },
            "tokens": {
                "total_input": 0,
                "total_output": 0,
                "total_cached": 0,
                "cache_savings_ratio": "0x"
            },
            "model_pools": [
                {"name": "Gemini 3.8 Flash", "status": "充足", "level": "normal"},
                {"name": "Gemini Pro", "status": "就绪", "level": "normal"},
                {"name": "Claude 3.5 Sonnet", "status": "可用", "level": "normal"}
            ]
        },
        "details": {}
    }

    try:
        # 1. Check running processes
        ps_output = subprocess.check_output(["ps", "-axo", "pid,command"], text=True, stderr=subprocess.DEVNULL)
        
        main_pids = []
        ls_pids = []
        
        for line in ps_output.splitlines():
            line_strip = line.strip()
            if "grep" in line_strip:
                continue
            
            # Check main Antigravity app
            if "Antigravity.app/Contents/MacOS/Antigravity" in line_strip:
                parts = line_strip.split(None, 1)
                if parts:
                    main_pids.append(int(parts[0]))
            
            # Check language_server
            if "language_server" in line_strip and "antigravity" in line_strip:
                parts = line_strip.split(None, 1)
                if parts:
                    ls_pids.append(int(parts[0]))
                    ver_match = re.search(r"--override_ide_version\s+([^\s]+)", line_strip)
                    if ver_match:
                        status["version"] = ver_match.group(1)
                    
                    bridge_match = re.search(r"--host_bridge_url=([^\s]+)", line_strip)
                    if bridge_match:
                        status["host_bridge_url"] = bridge_match.group(1)

            # Check if agy-zh or chinese overlay is active
            if "antigravity-hans" in line_strip or "agy-zh" in line_strip:
                status["is_chinese_launcher"] = True

        if main_pids:
            status["running"] = True
            status["pid"] = main_pids[0]
            status["details"]["worker_processes"] = len(main_pids)
        
        if ls_pids:
            status["language_server_running"] = True
            status["language_server_pid"] = ls_pids[0]

        # 2. Extract Token Quota & Context Window from local transcripts
        brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
        if os.path.exists(brain_dir):
            convs = [d for d in os.listdir(brain_dir) if os.path.isdir(os.path.join(brain_dir, d)) and not d.startswith(".")]
            status["active_conversations_count"] = len(convs)

            jsonl_files = glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl"))
            
            total_input = 0
            total_output = 0
            total_cached = 0
            five_hour_tokens = 0
            oldest_step_in_5h = None
            now_ts = time.time()
            five_hours_ago = now_ts - (5 * 3600)
            
            latest_step = None
            latest_mtime = 0

            for fpath in jsonl_files:
                try:
                    mt = os.path.getmtime(fpath)
                    if mt > latest_mtime:
                        latest_mtime = mt
                    
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                obj = json.loads(line)
                                if "model" in obj:
                                    latest_step = obj
                                    m_inp = obj.get("input_tokens", 0)
                                    m_out = obj.get("output_tokens", 0)
                                    m_cached = obj.get("cache_read_tokens", 0)
                                    
                                    total_input += m_inp
                                    total_output += m_out
                                    total_cached += m_cached

                                    created_at = obj.get("created_at")
                                    if created_at:
                                        try:
                                            step_time = calendar.timegm(time.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S"))
                                            if step_time >= five_hours_ago:
                                                five_hour_tokens += (m_inp + m_out)
                                                if oldest_step_in_5h is None or step_time < oldest_step_in_5h:
                                                    oldest_step_in_5h = step_time
                                        except Exception:
                                            five_hour_tokens += (m_inp + m_out)
                            except Exception:
                                pass
                except Exception:
                    pass

            if latest_mtime > 0:
                status["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_mtime))

            # Update Quota & Context stats
            if latest_step:
                raw_model = latest_step.get("model", "gemini-3.8-flash-high")
                model_display = raw_model.replace("gemini-", "Gemini ").replace("-high", " (High)").replace("-low", " (Low)")
                status["quota"]["current_model"] = model_display

                inp = latest_step.get("input_tokens", 0)
                cached = latest_step.get("cache_read_tokens", 0)
                ctx_used = inp + cached
                max_ctx = 1000000  # 1M Context Window
                ctx_pct = round((ctx_used / max_ctx) * 100, 1)

                status["quota"]["context_window"] = {
                    "used_tokens": ctx_used,
                    "max_tokens": max_ctx,
                    "percent": ctx_pct,
                    "human": f"{ctx_used / 1000:.1f}k / 1.0M"
                }

            # 5-hour rolling usage calculation with exact rolling reset countdown
            est_limit = 1500000  # 1.5M tokens / 5h standard Pro window
            fh_pct = round(min(100.0, (five_hour_tokens / est_limit) * 100), 1)
            
            reset_str = "随时可用 (未消耗)"
            if oldest_step_in_5h is not None and five_hour_tokens > 0:
                reset_in_sec = max(0, int((oldest_step_in_5h + 5 * 3600) - now_ts))
                rh = reset_in_sec // 3600
                rm = (reset_in_sec % 3600) // 60
                reset_str = f"{rh}小时{rm:02d}分后开始滚动释放" if rh > 0 else f"{rm}分钟后开始释放"

            status["quota"]["five_hour_usage"] = {
                "used_tokens": five_hour_tokens,
                "limit_tokens": est_limit,
                "percent": fh_pct,
                "status": "critical" if fh_pct >= 90 else ("warning" if fh_pct >= 70 else "normal"),
                "reset_countdown_human": reset_str,
                "human_used": f"{five_hour_tokens / 1000:.1f}k / {est_limit / 1000000:.1f}M"
            }

            status["quota"]["tokens"] = {
                "total_input": total_input,
                "total_output": total_output,
                "total_cached": total_cached,
                "cache_savings_ratio": f"{round(total_cached / max(1, total_input), 1)}x"
            }

    except Exception as e:
        status["details"]["error"] = str(e)

    return status

if __name__ == "__main__":
    print(json.dumps(get_antigravity_status(), indent=2, ensure_ascii=False))
