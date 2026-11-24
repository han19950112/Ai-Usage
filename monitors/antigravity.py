#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Agent Monitor Module
Detects local Antigravity processes, language server status, IDE version,
active model, context window occupancy, 5-hour rolling quota, weekly quota,
and breakdown for two core model suites (Gemini & Claude/Pro).
"""

import calendar
import glob
import json
import os
import re
import subprocess
import time

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
                "limit_tokens": 1500000,
                "percent": 0.0,
                "status": "normal", # normal, warning, critical
                "reset_countdown_human": "随时可用 (未消耗)",
                "human_used": "0k / 1.5M"
            },
            "weekly_usage": {
                "used_tokens": 0,
                "limit_tokens": 10000000,
                "percent": 0.0,
                "status": "normal",
                "reset_countdown_human": "--",
                "human_used": "0.0M / 10.0M"
            },
            "tokens": {
                "total_input": 0,
                "total_output": 0,
                "total_cached": 0,
                "cache_savings_ratio": "0x"
            },
            # 两套模型独立额度池
            "dual_models": [
                {
                    "id": "model_gemini",
                    "name": "Gemini 3.8 Flash (主力套)",
                    "type": "高频编程/架构分析",
                    "five_hour_used": "0k",
                    "weekly_used": "0.0M",
                    "limit_label": "1.5M / 5h · 10M / 周",
                    "percent_5h": 0.0,
                    "percent_week": 0.0,
                    "status": "充足",
                    "level": "normal"
                },
                {
                    "id": "model_claude",
                    "name": "Claude 3.5 Sonnet / Pro (高阶套)",
                    "type": "高复杂度推理/精细代码重构",
                    "five_hour_used": "0k",
                    "weekly_used": "0.0M",
                    "limit_label": "独立高阶池 · 500k / 5h",
                    "percent_5h": 0.0,
                    "percent_week": 0.0,
                    "status": "就绪",
                    "level": "normal"
                }
            ],
            "model_pools": [
                {"name": "Gemini 3.8 Flash", "status": "充足", "level": "normal"},
                {"name": "Claude 3.5 Sonnet", "status": "可用", "level": "normal"},
                {"name": "Gemini Pro", "status": "就绪", "level": "normal"}
            ]
        },
        "details": {}
    }

    try:
        # 1. 检查运行进程
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

        # 2. 从本地会话 transcript 中解析 5小时配额、周配额及双模型消耗
        brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
        if os.path.exists(brain_dir):
            convs = [d for d in os.listdir(brain_dir) if os.path.isdir(os.path.join(brain_dir, d)) and not d.startswith(".")]
            status["active_conversations_count"] = len(convs)

            jsonl_files = glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl"))
            
            total_input = 0
            total_output = 0
            total_cached = 0
            
            five_hour_tokens = 0
            weekly_tokens = 0
            
            # 双模型统计
            gemini_5h_tokens = 0
            gemini_week_tokens = 0
            claude_5h_tokens = 0
            claude_week_tokens = 0
            
            oldest_step_in_5h = None
            now_ts = time.time()
            five_hours_ago = now_ts - (5 * 3600)
            seven_days_ago = now_ts - (7 * 86400)
            
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
                                    m_total = m_inp + m_out
                                    
                                    total_input += m_inp
                                    total_output += m_out
                                    total_cached += m_cached

                                    model_name = str(obj.get("model", "")).lower()
                                    is_claude_or_pro = any(k in model_name for k in ["claude", "sonnet", "pro", "gemini-pro"])

                                    created_at = obj.get("created_at")
                                    if created_at:
                                        try:
                                            step_time = calendar.timegm(time.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S"))
                                            
                                            # 5小时窗口统计
                                            if step_time >= five_hours_ago:
                                                five_hour_tokens += m_total
                                                if is_claude_or_pro:
                                                    claude_5h_tokens += m_total
                                                else:
                                                    gemini_5h_tokens += m_total
                                                    
                                                if oldest_step_in_5h is None or step_time < oldest_step_in_5h:
                                                    oldest_step_in_5h = step_time
                                            
                                            # 周窗口统计（最近7天）
                                            if step_time >= seven_days_ago:
                                                weekly_tokens += m_total
                                                if is_claude_or_pro:
                                                    claude_week_tokens += m_total
                                                else:
                                                    gemini_week_tokens += m_total

                                        except Exception:
                                            five_hour_tokens += m_total
                                            weekly_tokens += m_total
                                            gemini_5h_tokens += m_total
                                            gemini_week_tokens += m_total
                            except Exception:
                                pass
                except Exception:
                    pass

            if latest_mtime > 0:
                status["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_mtime))

            # 更新当前活跃模型与上下文窗口
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

            # 1. 5小时滚动用量计算
            est_limit_5h = 1500000  # 1.5M tokens / 5h 标准滑动上限
            fh_pct = round(min(100.0, (five_hour_tokens / est_limit_5h) * 100), 1)
            
            reset_5h_str = "随时可用 (未消耗)"
            if oldest_step_in_5h is not None and five_hour_tokens > 0:
                reset_in_sec = max(0, int((oldest_step_in_5h + 5 * 3600) - now_ts))
                rh = reset_in_sec // 3600
                rm = (reset_in_sec % 3600) // 60
                reset_5h_str = f"{rh}小时{rm:02d}分后开始滚动释放" if rh > 0 else f"{rm}分钟后开始释放"

            status["quota"]["five_hour_usage"] = {
                "used_tokens": five_hour_tokens,
                "limit_tokens": est_limit_5h,
                "percent": fh_pct,
                "status": "critical" if fh_pct >= 90 else ("warning" if fh_pct >= 70 else "normal"),
                "reset_countdown_human": reset_5h_str,
                "human_used": f"{five_hour_tokens / 1000:.1f}k / {est_limit_5h / 1000000:.1f}M"
            }

            # 2. 周额度统计（Weekly Quota，基准 10.0M Token / 周）
            est_limit_week = 10000000  # 10M tokens / 周
            week_pct = round(min(100.0, (weekly_tokens / est_limit_week) * 100), 1)
            
            # 计算到下周一 00:00 (UTC) 的到期倒计时
            utc_now = time.gmtime(now_ts)
            days_to_monday = (7 - utc_now.tm_wday) % 7
            if days_to_monday == 0 and (utc_now.tm_hour > 0 or utc_now.tm_min > 0):
                days_to_monday = 7
            next_reset_epoch = now_ts + (days_to_monday * 86400) - (utc_now.tm_hour * 3600 + utc_now.tm_min * 60 + utc_now.tm_sec)
            sec_left = max(0, int(next_reset_epoch - now_ts))
            left_days = sec_left // 86400
            left_hours = (sec_left % 86400) // 3600
            weekly_reset_str = f"{left_days}天{left_hours}小时后周重置"

            status["quota"]["weekly_usage"] = {
                "used_tokens": weekly_tokens,
                "limit_tokens": est_limit_week,
                "percent": week_pct,
                "status": "critical" if week_pct >= 90 else ("warning" if week_pct >= 75 else "normal"),
                "reset_countdown_human": weekly_reset_str,
                "human_used": f"{weekly_tokens / 1000000:.2f}M / {est_limit_week / 1000000:.1f}M"
            }

            # 3. 两套模型（双模型池）详细消耗分布
            # 模型 A: Gemini 3.8 Flash 主力套
            g_5h_pct = round(min(100.0, (gemini_5h_tokens / 1500000) * 100), 1)
            g_wk_pct = round(min(100.0, (gemini_week_tokens / 10000000) * 100), 1)
            
            # 模型 B: Claude 3.5 Sonnet / Pro 高阶套 (基准独立池 500k 5h / 2M 周)
            c_5h_pct = round(min(100.0, (claude_5h_tokens / 500000) * 100), 1)
            c_wk_pct = round(min(100.0, (claude_week_tokens / 2000000) * 100), 1)

            status["quota"]["dual_models"] = [
                {
                    "id": "model_gemini",
                    "name": "⚡ Gemini 3.8 Flash (主力套)",
                    "type": "高频编程 / 长上下文",
                    "five_hour_used": f"{gemini_5h_tokens / 1000:.1f}k",
                    "weekly_used": f"{gemini_week_tokens / 1000000:.2f}M",
                    "limit_label": "1.5M/5h · 10M/周",
                    "percent_5h": g_5h_pct,
                    "percent_week": g_wk_pct,
                    "status": "充足" if g_5h_pct < 70 else ("警示" if g_5h_pct < 90 else "紧张"),
                    "level": "normal" if g_5h_pct < 70 else "warning"
                },
                {
                    "id": "model_claude",
                    "name": "🧠 Claude 3.5 Sonnet / Pro (高阶套)",
                    "type": "复杂推理 / 精细重构",
                    "five_hour_used": f"{claude_5h_tokens / 1000:.1f}k",
                    "weekly_used": f"{claude_week_tokens / 1000000:.2f}M",
                    "limit_label": "独立高阶池 500k/5h",
                    "percent_5h": c_5h_pct,
                    "percent_week": c_wk_pct,
                    "status": "就绪 (独立配额)" if c_5h_pct < 50 else "已消耗",
                    "level": "normal"
                }
            ]

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
