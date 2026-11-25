#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy Agent Monitor & Auto-Checkin Engine
Handles WorkBuddy status detection, automated daily check-in (Buddy 加油站), and point tracking.
"""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import ssl
import urllib.request
import urllib.error
import uuid

# Live API cache (60s TTL) to avoid hammering www.workbuddy.cn every 2s
_WB_LIVE_CACHE = {"key": None, "ts": 0.0, "data": None}
_WB_CACHE_LOCK = threading.Lock()

def _get_ssl_context(config):
    ctx = ssl.create_default_context()
    if config.get("insecure_ssl", False):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _detect_local_workbuddy_uid():
    """Auto-detect local WorkBuddy UUID from ~/.workbuddy/<uuid> directory."""
    wb_dir = os.path.expanduser("~/.workbuddy")
    if not os.path.isdir(wb_dir):
        return ""
    try:
        for name in os.listdir(wb_dir):
            if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", name.lower()):
                return name
    except Exception:
        pass
    return ""

def _wb_headers(config):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.workbuddy.cn",
        "Referer": "https://www.workbuddy.cn/app",
        "x-request-id": str(uuid.uuid4()),
    }
    uid = str(config.get("user_id", "") or "").strip() or _detect_local_workbuddy_uid()
    if uid:
        headers["x-user-id"] = uid
    token = str(config.get("token", "") or "").strip()
    cookie = str(config.get("cookie", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}" if not token.lower().startswith("bearer ") else token
    if cookie:
        headers["Cookie"] = cookie
    return headers

def _fetch_workbuddy_live_data(config):
    """Fetch real credits, check-in status, and growth streak from www.workbuddy.cn."""
    token = str(config.get("token", "") or "").strip()
    cookie = str(config.get("cookie", "") or "").strip()
    if (not token and not cookie) or config.get("demo_mode", False) or token == "demo" or cookie == "demo":
        return None

    cache_key = hashlib.sha256(f"{token}|{cookie}".encode("utf-8")).hexdigest()
    now_ts = time.time()
    with _WB_CACHE_LOCK:
        if _WB_LIVE_CACHE["key"] == cache_key and (now_ts - _WB_LIVE_CACHE["ts"]) < 60.0:
            return _WB_LIVE_CACHE["data"]

    headers = _wb_headers(config)
    ssl_ctx = _get_ssl_context(config)
    result = {}

    def _req(url, method="POST", body=b"{}"):
        req = urllib.request.Request(url, data=(body if method == "POST" else None), headers=headers, method=method)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    # 1. Total credits & credit groups
    try:
        r = _req("https://www.workbuddy.cn/billing/meter/get-user-resource-summary", "POST", b"{}")
        d = r.get("data") or {}
        if isinstance(d, dict) and d.get("TotalCredits") is not None:
            result["total_points"] = round(float(d.get("TotalCredits") or 0), 2)
            result["plan_name"] = d.get("SubscriptionPackageName") or "体验版"
            groups = d.get("CreditGroups") or []
            total_cap = sum(float(g.get("CycleTotalCapacity") or 0) for g in groups)
            used_cap = sum(float(g.get("CycleUsedCapacity") or 0) for g in groups)
            if total_cap > 0:
                result["used_credits"] = round(used_cap, 2)
                result["total_credits_cap"] = round(total_cap, 2)
                result["used_percent"] = round(min(100.0, (used_cap / total_cap) * 100.0), 1)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            result["auth_expired"] = True
            result["summary_err"] = "登录态已失效 (HTTP 401)，请重新登录后更新 Cookie"
        else:
            result["summary_err"] = f"HTTP {e.code}"
    except Exception as e:
        result["summary_err"] = str(e)

    # 2. Checkin status (Buddy 加油站)
    try:
        r = _req("https://www.workbuddy.cn/billing/meter/checkin-status", "POST", b"{}")
        d = r.get("data") or {}
        if isinstance(d, dict):
            result["checkin_active"] = bool(d.get("active", False))
            result["today_checked_in"] = bool(d.get("today_checked_in", False))
            result["checkin_streak_days"] = int(d.get("streak_days") or 0)
    except Exception:
        pass

    # 3. Growth center streak (活跃连登天数)
    try:
        r = _req("https://www.workbuddy.cn/activity/growth/streak", "GET")
        d = r.get("data") or {}
        streak = d.get("streak") or {}
        if isinstance(streak, dict):
            result["growth_streak_days"] = int(streak.get("days") or 0)
            result["month_total_days"] = int(streak.get("month_total_days") or 0)
    except Exception:
        pass

    with _WB_CACHE_LOCK:
        _WB_LIVE_CACHE["key"] = cache_key
        _WB_LIVE_CACHE["ts"] = now_ts
        _WB_LIVE_CACHE["data"] = result if result else None
    return result if result else None

_LOCAL_HISTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checkin_history.json")
_USER_HISTORY = os.path.expanduser("~/.agent-cockpit/checkin_history.json")
if os.path.exists(_LOCAL_HISTORY):
    HISTORY_FILE = _LOCAL_HISTORY
else:
    HISTORY_FILE = _USER_HISTORY

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"records": []}
    return {"records": []}

def save_history(history):
    try:
        parent_dir = os.path.dirname(HISTORY_FILE)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WorkBuddy] 保存历史失败: {e}")

def run_workbuddy_checkin(config=None, force=False):
    if config is None:
        config = {}

    today_str = time.strftime("%Y-%m-%d")
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    history = load_history()
    records = history.get("records", [])

    # Check if already checked in today
    today_records = [r for r in records if r.get("date") == today_str and r.get("success")]
    if today_records and not force:
        return {
            "success": True,
            "already_done": True,
            "message": f"今日 ({today_str}) 已签到完成",
            "last_record": today_records[-1]
        }

    token = config.get("token", "").strip()
    cookie = config.get("cookie", "").strip()
    api_url = config.get("checkin_url", "https://www.workbuddy.cn/billing/meter/checkin").strip()
    if "workbuddy.qq.com" in api_url:
        api_url = "https://www.workbuddy.cn/billing/meter/checkin"
    demo_mode = config.get("demo_mode", False)

    if not token and not cookie and not demo_mode:
        record = {
            "date": today_str,
            "time": now_str,
            "success": False,
            "message": "未配置 WorkBuddy Token 或 Cookie，请在设置中填写凭据"
        }
        return {"success": False, "message": record["message"], "record": record}

    # Demo mode simulation
    if demo_mode or (token == "demo" or cookie == "demo"):
        last_ok = next((r for r in reversed(records) if r.get("success")), None)
        prev_pts = int(last_ok.get("total_points", 1750)) if last_ok else 1750
        prev_days = int(last_ok.get("consecutive_days", 2)) if last_ok else 2
        new_pts = prev_pts + 100
        new_days = prev_days + (0 if today_records else 1)
        record = {
            "date": today_str,
            "time": now_str,
            "success": True,
            "message": "签到成功！获得 +100 积分 (演示模式)",
            "reward_points": 100,
            "consecutive_days": new_days,
            "total_points": new_pts
        }
        records.append(record)
        history["records"] = records[-50:]
        save_history(history)
        return {"success": True, "message": record["message"], "record": record}

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) WorkBuddy/1.0.0",
        "Content-Type": "application/json"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie

    ssl_ctx = _get_ssl_context(config)
    try:
        payload = json.dumps({"source": "desktop_client", "action": "daily_checkin"}).encode("utf-8")
        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            res_data = json.loads(body)
            
            # Parse typical return format
            code = res_data.get("code", res_data.get("status", 0))
            is_ok = code in (0, 200, "0", "200", "SUCCESS")
            msg = res_data.get("msg", res_data.get("message", "签到请求已处理"))
            data_field = res_data.get("data") or {}
            if not isinstance(data_field, dict):
                data_field = {}
            
            reward = data_field.get("points", data_field.get("bonus", data_field.get("reward", 100)))
            total = data_field.get("total_points", data_field.get("current_points", 0))
            consec = data_field.get("consecutive_days", 1)

            record = {
                "date": today_str,
                "time": now_str,
                "success": is_ok,
                "message": msg if is_ok else f"签到返回异常: {msg}",
                "reward_points": reward if is_ok else 0,
                "consecutive_days": consec,
                "total_points": total
            }
            records.append(record)
            history["records"] = records[-50:]
            save_history(history)
            return {"success": is_ok, "message": record["message"], "record": record}

    except urllib.error.HTTPError as e:
        err_msg = f"HTTP 错误: {e.code} {e.reason}"
        record = {
            "date": today_str,
            "time": now_str,
            "success": False,
            "message": err_msg
        }
        records.append(record)
        history["records"] = records[-50:]
        save_history(history)
        return {"success": False, "message": err_msg, "record": record}
    except Exception as e:
        err_msg = f"请求失败: {str(e)}"
        record = {
            "date": today_str,
            "time": now_str,
            "success": False,
            "message": err_msg
        }
        records.append(record)
        history["records"] = records[-50:]
        save_history(history)
        return {"success": False, "message": err_msg, "record": record}

def get_workbuddy_status(config=None):
    if config is None:
        config = {}

    status = {
        "name": "WorkBuddy (腾讯全场景 Agent)",
        "running": False,
        "pid": None,
        "configured": False,
        "auto_checkin_enabled": config.get("auto_checkin_enabled", True),
        "checkin_time": config.get("checkin_time", "09:00"),
        "today_checked_in": False,
        "last_checkin_time": None,
        "last_checkin_message": "暂无记录",
        "consecutive_days": 0,
        "total_points": 0,
        "five_hour_usage": {
            "used_requests": 12 if config.get("demo_mode") else 0,
            "limit_requests": 100,
            "percent": 12.0 if config.get("demo_mode") else 0.0,
            "status": "normal",
            "reset_countdown_human": "5小时滑动重置",
            "human_used": "12 / 100 次" if config.get("demo_mode") else "0 / 100 次"
        },
        "recent_history": []
    }

    # 1. Process check
    my_pid = os.getpid()
    try:
        ps_output = subprocess.check_output(["ps", "-axo", "pid,command"], text=True, stderr=subprocess.DEVNULL)
        for line in ps_output.splitlines():
            line_strip = line.strip()
            if "grep" in line_strip or "workbuddy.py" in line_strip:
                continue
            parts = line_strip.split(None, 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
                if pid == my_pid:
                    continue
            except ValueError:
                continue
            cmd = parts[1].lower() if len(parts) > 1 else ""
            if any(k in cmd for k in ["/workbuddy", "workbuddy.app", "codebuddy.app", "bin/workbuddy"]):
                status["running"] = True
                status["pid"] = pid
                break
    except Exception:
        pass

    # 2. Config check
    if config.get("token") or config.get("cookie") or config.get("demo_mode"):
        status["configured"] = True

    # 3. Read history
    today_str = time.strftime("%Y-%m-%d")
    history = load_history()
    records = history.get("records", [])
    status["recent_history"] = records[-5:]

    if records:
        last = records[-1]
        status["last_checkin_time"] = last.get("time")
        status["last_checkin_message"] = last.get("message", "")
        # 从最近一次成功记录恢复积分与连续天数，避免单次网络失败导致积分归零
        last_success = next((r for r in reversed(records) if r.get("success")), None)
        if last_success:
            status["consecutive_days"] = last_success.get("consecutive_days", 0)
            status["total_points"] = last_success.get("total_points", 0)

    # Check today
    for r in reversed(records):
        if r.get("date") == today_str and r.get("success"):
            status["today_checked_in"] = True
            break

    # 4. Merge live www.workbuddy.cn data when authenticated
    live = _fetch_workbuddy_live_data(config)
    if live:
        if live.get("auth_expired"):
            status["last_checkin_message"] = live.get("summary_err", "登录态已失效，请重新更新 Cookie")
        if "total_points" in live:
            status["total_points"] = live["total_points"]
        if live.get("checkin_streak_days", 0) > 0:
            status["consecutive_days"] = live["checkin_streak_days"]
        elif live.get("growth_streak_days", 0) > 0:
            status["consecutive_days"] = live["growth_streak_days"]
        if live.get("today_checked_in"):
            status["today_checked_in"] = True
        if "total_credits_cap" in live:
            pct = live.get("used_percent", 0.0)
            status["five_hour_usage"] = {
                "used_requests": live.get("used_credits", 0),
                "limit_requests": live.get("total_credits_cap", 0),
                "percent": pct,
                "status": "critical" if pct >= 90 else ("warning" if pct >= 70 else "normal"),
                "reset_countdown_human": f"{live.get('plan_name', '体验版')} · 月累计活跃 {live.get('month_total_days', 0)} 天",
                "human_used": f"已用 {live.get('used_credits', 0)} / {live.get('total_credits_cap', 0)} 积分"
            }

    return status

if __name__ == "__main__":
    print(json.dumps(get_workbuddy_status({}), indent=2, ensure_ascii=False))
