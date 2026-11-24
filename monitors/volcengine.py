#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volcano Engine (火山引擎) Plan API Monitor Module
Tracks Volcengine Ark Coding Plan / Agent Plan usage, 5h rolling window, weekly/monthly quotas.
"""

import calendar
from datetime import datetime
import json
import ssl
import time
import urllib.request
import urllib.error

def _get_ssl_context(config):
    ctx = ssl.create_default_context()
    if config.get("insecure_ssl", False):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _calc_window_resets(now_ts):
    """Calculate standard 5h, weekly (Monday 00:00 UTC), and monthly (1st 00:00 local) reset info."""
    # Weekly: next Monday 00:00 UTC
    utc_now = time.gmtime(now_ts)
    days_to_monday = (7 - utc_now.tm_wday) % 7
    if days_to_monday == 0 and (utc_now.tm_hour > 0 or utc_now.tm_min > 0 or utc_now.tm_sec > 0):
        days_to_monday = 7
    next_week_epoch = now_ts + (days_to_monday * 86400) - (utc_now.tm_hour * 3600 + utc_now.tm_min * 60 + utc_now.tm_sec)
    sec_left_wk = max(0, int(next_week_epoch - now_ts))
    wk_days = sec_left_wk // 86400
    wk_hours = (sec_left_wk % 86400) // 3600
    wk_countdown = f"{wk_days}天{wk_hours}小时后重置"
    wk_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(next_week_epoch))

    # Monthly: 1st of next month 00:00 local time
    dt_now = datetime.fromtimestamp(now_ts)
    if dt_now.month == 12:
        next_month_dt = datetime(dt_now.year + 1, 1, 1, 0, 0, 0)
    else:
        next_month_dt = datetime(dt_now.year, dt_now.month + 1, 1, 0, 0, 0)
    sec_left_mo = max(0, int(next_month_dt.timestamp() - now_ts))
    mo_days = sec_left_mo // 86400
    mo_hours = (sec_left_mo % 86400) // 3600
    mo_countdown = f"{mo_days}天{mo_hours}小时后重置"
    mo_expire = next_month_dt.strftime("%Y-%m-%d %H:%M:%S")

    return wk_countdown, wk_expire, mo_countdown, mo_expire

def _quota_level(pct):
    if pct >= 90:
        return "critical"
    if pct >= 75:
        return "warning"
    return "normal"

def get_volcengine_plan_status(config=None):
    if config is None:
        config = {}

    now_ts = int(time.time())
    wk_countdown, wk_expire, mo_countdown, mo_expire = _calc_window_resets(now_ts)

    plan_expire_date = str(config.get("plan_expire_date", "") or "").strip()
    plan_expire_human = "未设置"
    if plan_expire_date:
        try:
            exp_dt = datetime.strptime(plan_expire_date[:10], "%Y-%m-%d")
            days_left = (exp_dt.date() - datetime.fromtimestamp(now_ts).date()).days
            if days_left > 0:
                plan_expire_human = f"{plan_expire_date[:10]} (剩余 {days_left} 天)"
            elif days_left == 0:
                plan_expire_human = f"{plan_expire_date[:10]} (今日到期)"
            else:
                plan_expire_human = f"{plan_expire_date[:10]} (已过期 {abs(days_left)} 天)"
        except Exception:
            plan_expire_human = plan_expire_date

    status = {
        "name": "火山引擎 Coding/Agent Plan",
        "configured": False,
        "healthy": False,
        "latency_ms": None,
        "mode": "API Key / Token",
        "plan_expire_date": plan_expire_date,
        "plan_expire_human": plan_expire_human,
        "five_hour_quota": {
            "used": 0,
            "total": 100,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_seconds": 0,
            "reset_countdown_human": "5小时滑动重置",
            "reset_expire_time": "随时可用",
            "human_used": "0 / 100 次"
        },
        "weekly_quota": {
            "used": 0,
            "total": 100,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": wk_countdown,
            "reset_expire_time": wk_expire,
            "human_used": "待同步"
        },
        "monthly_quota": {
            "used": 0,
            "total": 100,
            "percent": 0.0,
            "status": "normal",
            "reset_countdown_human": mo_countdown,
            "reset_expire_time": mo_expire,
            "human_used": "待同步"
        },
        "model_name": config.get("model", "doubao-seed-evolving"),
        "last_check_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": "未配置 API 凭证"
    }

    api_key = config.get("api_key", "").strip()
    ak = config.get("ak", "").strip()
    sk = config.get("sk", "").strip()
    base_url = config.get("base_url", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    # ark- 前缀为方舟 Coding Plan 专属 Key，自动适配 /api/coding/v3 网关
    coding_base_url = "https://ark.cn-beijing.volces.com/api/coding/v3" if (api_key.startswith("ark-") and base_url.endswith("/api/v3")) else base_url

    # If demo mode is explicitly enabled for preview
    if config.get("demo_mode", False):
        status["configured"] = True
        status["healthy"] = True
        status["latency_ms"] = 48
        status["mode"] = "演示模式"
        if not plan_expire_date:
            status["plan_expire_human"] = "2026-12-31 (演示订阅)"
        demo_5h_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts + 3840))
        status["five_hour_quota"] = {
            "used": 42000,
            "total": 100000,
            "percent": 42.0,
            "status": "normal",
            "reset_countdown_seconds": 3840,
            "reset_countdown_human": "1小时04分后开始释放",
            "reset_expire_time": demo_5h_expire,
            "human_used": "42k / 100k"
        }
        status["weekly_quota"] = {
            "used": 280000,
            "total": 1000000,
            "percent": 28.0,
            "status": "normal",
            "reset_countdown_human": wk_countdown,
            "reset_expire_time": wk_expire,
            "human_used": "280k / 1.0M"
        }
        status["monthly_quota"] = {
            "used": 1150000,
            "total": 5000000,
            "percent": 23.0,
            "status": "normal",
            "reset_countdown_human": mo_countdown,
            "reset_expire_time": mo_expire,
            "human_used": "1.15M / 5.0M"
        }
        status["message"] = "演示模式已开启 (模拟配额)"
        return status

    if not api_key and not ak:
        status["configured"] = False
        status["message"] = "请在 config.json 中配置 api_key 或 ak/sk"
        return status

    status["configured"] = True
    ssl_ctx = _get_ssl_context(config)

    # Attempt to query Volcano Ark usage
    start_time = time.time()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    try:
        # 1. Try usage endpoint first (for custom proxy / future Ark endpoint)
        check_url = f"{coding_base_url}/coding_plan/usage"
        req = urllib.request.Request(check_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp:
            latency = int((time.time() - start_time) * 1000)
            status["latency_ms"] = latency
            status["healthy"] = True
            status["message"] = f"连接正常 ({latency}ms)"
            
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            plan_data = data.get("data", data)
            
            # 5h window
            five_h = plan_data.get("five_hour", {})
            used_5h = five_h.get("used", 0)
            total_5h = five_h.get("total", 1) or 1
            pct_5h = round((used_5h / total_5h) * 100, 1)
            countdown = int(five_h.get("reset_in_seconds", 0) or 0)
            expire_5h = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts + countdown)) if countdown > 0 else "随时可用"
            
            status["five_hour_quota"] = {
                "used": used_5h,
                "total": total_5h,
                "percent": pct_5h,
                "status": _quota_level(pct_5h),
                "reset_countdown_seconds": countdown,
                "reset_countdown_human": f"{countdown // 60}分后开始释放" if countdown < 3600 else f"{countdown // 3600}小时{(countdown % 3600) // 60}分后开始释放",
                "reset_expire_time": expire_5h,
                "human_used": f"{used_5h // 1000}k / {total_5h // 1000}k"
            }
            
            # Weekly window
            week = plan_data.get("weekly", {})
            used_w = week.get("used", 0)
            total_w = week.get("total", 1) or 1
            pct_w = round((used_w / total_w) * 100, 1)
            status["weekly_quota"] = {
                "used": used_w,
                "total": total_w,
                "percent": pct_w,
                "status": _quota_level(pct_w),
                "reset_countdown_human": wk_countdown,
                "reset_expire_time": wk_expire,
                "human_used": f"{used_w // 1000}k / {total_w // 1000}k"
            }

            # Monthly window
            month = plan_data.get("monthly", {})
            used_m = month.get("used", 0)
            total_m = month.get("total", 1) or 1
            pct_m = round((used_m / total_m) * 100, 1)
            status["monthly_quota"] = {
                "used": used_m,
                "total": total_m,
                "percent": pct_m,
                "status": _quota_level(pct_m),
                "reset_countdown_human": mo_countdown,
                "reset_expire_time": mo_expire,
                "human_used": f"{used_m // 1000}k / {total_m // 1000}k"
            }

    except urllib.error.HTTPError as e:
        # 2. 官方推理 API Key 不开放 /coding_plan/usage（返回 404），改为 0-Token 鉴权连通探测
        if e.code in (404, 405):
            probe_start = time.time()
            probe_url = f"{coding_base_url}/chat/completions"
            p_req = urllib.request.Request(probe_url, data=b"{}", headers=headers, method="POST")
            try:
                with urllib.request.urlopen(p_req, context=ssl_ctx, timeout=6):
                    status["latency_ms"] = int((time.time() - probe_start) * 1000)
                    status["healthy"] = True
            except urllib.error.HTTPError as pe:
                status["latency_ms"] = int((time.time() - probe_start) * 1000)
                if pe.code == 400:
                    # 400 MissingParameter 说明 Bearer API Key 已通过官方鉴权，且未消耗任何 Token
                    status["healthy"] = True
                    status["mode"] = "Coding Plan API Key" if api_key.startswith("ark-") else "Ark API Key"
                    status["message"] = "API Key 鉴权有效 · 推理通道畅通（官方推理 Key 不开放剩余额度接口，详见方舟控制台）"
                    status["five_hour_quota"]["reset_countdown_human"] = "5小时滚动窗口"
                    status["five_hour_quota"]["reset_expire_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts + 5 * 3600))
                    status["five_hour_quota"]["human_used"] = "通道就绪 (需控制台/AK查看余量)"
                    status["weekly_quota"]["human_used"] = "需控制台/AK查看"
                    status["monthly_quota"]["human_used"] = "需控制台/AK查看"
                elif pe.code in (401, 403):
                    status["healthy"] = False
                    status["message"] = f"API Key 鉴权失败: HTTP {pe.code}"
                else:
                    status["healthy"] = False
                    status["message"] = f"方舟接口返回: HTTP {pe.code} {pe.reason}"
            except Exception as pe:
                status["healthy"] = False
                status["message"] = f"通道探测失败: {str(pe)}"
        else:
            status["latency_ms"] = int((time.time() - start_time) * 1000)
            status["healthy"] = False
            status["message"] = f"鉴权或服务异常: HTTP {e.code}"
    except Exception as e:
        status["healthy"] = False
        status["message"] = f"网络请求失败: {str(e)}"

    return status

if __name__ == "__main__":
    print(json.dumps(get_volcengine_plan_status({}), indent=2, ensure_ascii=False))
