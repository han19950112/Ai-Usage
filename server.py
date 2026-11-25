#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Cockpit - Multi-Agent Unified Dashboard & Scheduler Server
Full AG-UI Protocol 1.0 Implementation:
1. Real-time Event Streaming (SSE)
2. Agent Chat & Command Streaming (RunAgent & TextMessageChunk)
3. Human-in-the-Loop 90% Circuit Breaker & Approval Flow
Zero external dependencies, built purely on Python standard library.
"""

import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

# Add current directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from monitors.antigravity import get_antigravity_status
from monitors.codex import get_codex_status
from monitors.volcengine import get_volcengine_plan_status
from monitors.workbuddy import get_workbuddy_status, run_workbuddy_checkin
import mission_control as mc
import agent_runner as runner

# Storage configuration
USER_DATA_DIR = os.path.expanduser("~/.agent-cockpit")
if os.path.exists(os.path.join(BASE_DIR, "config.json")):
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
    CHECKIN_HISTORY_FILE = os.path.join(BASE_DIR, "checkin_history.json")
else:
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    CONFIG_FILE = os.path.join(USER_DATA_DIR, "config.json")
    CHECKIN_HISTORY_FILE = os.path.join(USER_DATA_DIR, "checkin_history.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] 加载失败，使用默认配置: {e}")
    # Return default
    return {
        "server": {"host": "0.0.0.0", "port": 5999},
        "volcengine": {"enabled": True, "demo_mode": False},
        "workbuddy": {"enabled": True, "demo_mode": False, "auto_checkin_enabled": True, "checkin_time": "09:00"}
    }

def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass
        return True
    except Exception as e:
        print(f"[Config] 保存失败: {e}")
        return False

def _mask_secret(val):
    if not val:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    return (s[:4] + "****" + s[-4:]) if len(s) > 8 else "****"

def _is_valid_hhmm(val):
    if not isinstance(val, str):
        return False
    m = re.match(r"^(\d{2}):(\d{2})$", val.strip())
    if not m:
        return False
    hh, mm = int(m.group(1)), int(m.group(2))
    return 0 <= hh <= 23 and 0 <= mm <= 59

def send_macos_notification(title, message, subtitle="Agent Cockpit"):
    """Send a non-blocking native macOS notification via osascript (zero external dependencies)."""
    if sys.platform != "darwin":
        return
    try:
        def _esc(s):
            return str(s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")[:180]
        script = f'display notification "{_esc(message)}" with title "{_esc(title)}" subtitle "{_esc(subtitle)}"'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# =========================================================================
# AG-UI Event Hub & Circuit Breaker Engine
# =========================================================================

class AGUIEventHub:
    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()

    def register_client(self):
        q = queue.Queue(maxsize=128)
        with self.lock:
            self.clients.add(q)
        return q

    def unregister_client(self, q):
        with self.lock:
            self.clients.discard(q)

    def broadcast_event(self, event_name, payload):
        formatted = f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        with self.lock:
            stale = []
            for q in self.clients:
                try:
                    q.put_nowait(formatted)
                except queue.Full:
                    stale.append(q)
            for q in stale:
                self.clients.discard(q)

    def broadcast_raw(self, raw_bytes):
        with self.lock:
            stale = []
            for q in self.clients:
                try:
                    q.put_nowait(raw_bytes)
                except queue.Full:
                    stale.append(q)
            for q in stale:
                self.clients.discard(q)

    # Alias for convenience
    broadcast = broadcast_event

EVENT_HUB = AGUIEventHub()

# 90% 额度熔断与人机协同审批状态
CIRCUIT_BREAKER = {
    "triggered": False,
    "threshold": 90.0,
    "agent": None,
    "current_usage": 0.0,
    "message": "",
    "timestamp": None,
    "resolution": None,
    "paused": False,
    "dismissed_until": 0,
    "options": [
        {"id": "switch_backup", "label": "🔄 自动切换到高阶备用模型池 (Claude 3.5 Sonnet / Pro)", "action": "switch"},
        {"id": "pause_tasks", "label": "⏸️ 暂停自动化后台调度并等待滑动窗口重置", "action": "pause"},
        {"id": "ignore_warning", "label": "⚠️ 保持现状并强制继续运行", "action": "ignore"}
    ]
}

# Global state cache
LATEST_STATUS = {
    "server_time": "",
    "hostname": socket.gethostname(),
    "ag_ui_protocol": "1.0",
    "circuit_breaker": dict(CIRCUIT_BREAKER),
    "antigravity": {},
    "codex": {},
    "volcengine": {},
    "workbuddy": {},
    "mission_control": {}
}

STATUS_LOCK = threading.Lock()

def _status_fingerprint(ag, cdx, wb, volc, cb):
    """Build a lightweight comparable tuple to detect meaningful state changes."""
    return (
        ag.get("running"),
        ag.get("language_server_running"),
        ag.get("data_source"),
        ag.get("quota", {}).get("current_model"),
        ag.get("quota", {}).get("five_hour_usage", {}).get("percent"),
        ag.get("quota", {}).get("weekly_usage", {}).get("percent"),
        ag.get("quota", {}).get("context_window", {}).get("used_tokens"),
        cdx.get("running"),
        cdx.get("total_log_events"),
        cdx.get("five_hour_usage", {}).get("percent"),
        cdx.get("weekly_usage", {}).get("percent"),
        wb.get("running"),
        wb.get("today_checked_in"),
        wb.get("total_points"),
        wb.get("last_checkin_time"),
        volc.get("healthy"),
        volc.get("configured"),
        volc.get("five_hour_quota", {}).get("percent"),
        cb.get("triggered"),
        cb.get("paused"),
    )

def update_all_status(notify=True):
    global LATEST_STATUS
    cfg = load_config()
    
    ag = get_antigravity_status()
    cdx = get_codex_status()
    volc = get_volcengine_plan_status(cfg.get("volcengine", {}))
    wb = get_workbuddy_status(cfg.get("workbuddy", {}))

    with STATUS_LOCK:
        LATEST_STATUS["server_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        LATEST_STATUS["antigravity"] = ag
        LATEST_STATUS["codex"] = cdx
        LATEST_STATUS["volcengine"] = volc
        LATEST_STATUS["workbuddy"] = wb
        LATEST_STATUS["circuit_breaker"] = dict(CIRCUIT_BREAKER)
        LATEST_STATUS["mission_control"] = mc.get_snapshot()
        snapshot = dict(LATEST_STATUS)

    try:
        mc.record_usage_snapshot(snapshot, min_interval_sec=600)
    except Exception:
        pass

    if notify:
        EVENT_HUB.broadcast_event("STATE_DELTA", snapshot)

def background_scheduler():
    """Background scheduler thread for periodic metrics, daily check-ins, and AG-UI event ticks."""
    print("[AG-UI Engine] 智能体实时事件与熔断调度线程已就绪 (AG-UI Protocol 1.0)")
    
    update_all_status(notify=False)
    
    cfg = load_config()
    wb_cfg = cfg.get("workbuddy", {})
    if wb_cfg.get("auto_checkin_enabled", True) and (wb_cfg.get("token") or wb_cfg.get("cookie") or wb_cfg.get("demo_mode")):
        res = run_workbuddy_checkin(wb_cfg, force=False)
        print(f"[WorkBuddy] 启动自检签到: {res.get('message')}")
        update_all_status(notify=True)

    last_volc_check = time.time()
    last_fast_check = time.time()
    last_heartbeat = time.time()
    last_day_checked = ""
    last_wb_expired_notified_day = ""
    last_fp = None

    while True:
        try:
            now_ts = time.time()
            now = time.localtime(now_ts)
            current_time_str = time.strftime("%H:%M", now)
            today_str = time.strftime("%Y-%m-%d", now)
            cfg = load_config()
            target_time = cfg.get("workbuddy", {}).get("checkin_time", "09:00")

            with STATUS_LOCK:
                is_paused = CIRCUIT_BREAKER.get("paused", False)

            # 1. 每日定时自动打卡检查 (若处于熔断挂起状态则跳过)
            if (not is_paused and current_time_str == target_time and last_day_checked != today_str):
                wb_cfg = cfg.get("workbuddy", {})
                if wb_cfg.get("auto_checkin_enabled", True):
                    print(f"[WorkBuddy] 触发每日定时签到 ({target_time})")
                    res = run_workbuddy_checkin(wb_cfg, force=False)
                    print(f"[WorkBuddy] 定时签到结果: {res.get('message')}")
                    last_day_checked = today_str
                    if res.get("success") and not res.get("already_done"):
                        send_macos_notification("🎁 WorkBuddy 每日签到成功", res.get("message", "已领取每日积分"))
                    elif not res.get("success"):
                        send_macos_notification("⚠️ WorkBuddy 定时签到失败", res.get("message", "请检查 Cookie 是否过期"))
                    update_all_status(notify=True)

            # 2. 定时状态轮询与 90% 熔断监测 (Fast Poll: 2s)
            if now_ts - last_fast_check >= 2.0:
                last_fast_check = now_ts
                ag = get_antigravity_status()
                cdx = get_codex_status()
                wb = get_workbuddy_status(cfg.get("workbuddy", {}))

                # WorkBuddy Cookie 过期每日首次系统通知提醒
                if wb.get("auth_expired") and last_wb_expired_notified_day != today_str:
                    last_wb_expired_notified_day = today_str
                    send_macos_notification("🔑 WorkBuddy Cookie 已过期", "请重新登录 www.workbuddy.cn 并更新 Cookie 以恢复自动签到")
                
                # --- 90% 熔断阈值检测 ---
                ag_pct = ag.get("quota", {}).get("five_hour_usage", {}).get("percent", 0.0)
                trigger_payload = None
                with STATUS_LOCK:
                    if ag_pct < CIRCUIT_BREAKER["threshold"]:
                        # 水位回落至安全线以下时自动解除挂起与冷却
                        if CIRCUIT_BREAKER.get("paused"):
                            CIRCUIT_BREAKER["paused"] = False
                        if CIRCUIT_BREAKER.get("dismissed_until", 0) > 0:
                            CIRCUIT_BREAKER["dismissed_until"] = 0
                    elif ag_pct >= CIRCUIT_BREAKER["threshold"]:
                        if not CIRCUIT_BREAKER["triggered"] and now_ts >= CIRCUIT_BREAKER.get("dismissed_until", 0):
                            CIRCUIT_BREAKER["triggered"] = True
                            CIRCUIT_BREAKER["agent"] = "Google Antigravity"
                            CIRCUIT_BREAKER["current_usage"] = ag_pct
                            CIRCUIT_BREAKER["message"] = f"Antigravity 5小时额度已达 {ag_pct}%，触碰 90% 警戒线！即将面临 Google 官方阶梯限流。"
                            CIRCUIT_BREAKER["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                            trigger_payload = dict(CIRCUIT_BREAKER)

                    volc_curr = LATEST_STATUS.get("volcengine", {})
                    curr_fp = _status_fingerprint(ag, cdx, wb, volc_curr, CIRCUIT_BREAKER)
                    changed = (curr_fp != last_fp)
                    last_fp = curr_fp

                    LATEST_STATUS["server_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    LATEST_STATUS["antigravity"] = ag
                    LATEST_STATUS["codex"] = cdx
                    LATEST_STATUS["workbuddy"] = wb
                    LATEST_STATUS["circuit_breaker"] = dict(CIRCUIT_BREAKER)
                    snapshot = dict(LATEST_STATUS)

                if trigger_payload:
                    EVENT_HUB.broadcast_event("HUMAN_INTERACTION_REQUIRED", trigger_payload)
                    send_macos_notification("🚨 90% 额度安全熔断", trigger_payload.get("message", "请尽快处理人机协同审批"))

                if changed:
                    EVENT_HUB.broadcast_event("STATE_DELTA", snapshot)

            # 3. 每 1 秒广播时钟流（平滑倒计时）
            EVENT_HUB.broadcast_event("AGENT_TICK", {
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": int(now_ts)
            })

            # 4. 每 15 秒心跳保活
            if now_ts - last_heartbeat >= 15.0:
                last_heartbeat = now_ts
                EVENT_HUB.broadcast_raw(b": ping\n\n")

            # 5. 火山引擎 API 远端同步
            volc_interval = max(30, int(cfg.get("volcengine", {}).get("check_interval_seconds", 300)))
            if not is_paused and (now_ts - last_volc_check >= volc_interval):
                update_all_status(notify=True)
                last_volc_check = now_ts

        except Exception as e:
            print(f"[Scheduler Error] {e}")

        time.sleep(1.0)

# =========================================================================
# Multi-threaded HTTP Request Handler with AG-UI Interactive Endpoints
# =========================================================================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class CockpitHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cache-Control")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            index_path = os.path.join(BASE_DIR, "web", "index.html")
            if os.path.exists(index_path):
                with open(index_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "index.html not found")
            return

        # AG-UI 标准 SSE 实时事件通道
        if path in ("/api/events", "/ag-ui/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            client_queue = EVENT_HUB.register_client()
            with STATUS_LOCK:
                initial_snapshot = dict(LATEST_STATUS)
            init_msg = f"event: STATE_SNAPSHOT\ndata: {json.dumps(initial_snapshot, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(init_msg)
                self.wfile.flush()
            except Exception:
                EVENT_HUB.unregister_client(client_queue)
                return

            try:
                while True:
                    try:
                        msg = client_queue.get(timeout=25.0)
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                EVENT_HUB.unregister_client(client_queue)
            return

        if path == "/api/status":
            with STATUS_LOCK:
                data = dict(LATEST_STATUS)
            self.send_json(data)
            return

        if path == "/api/mc/snapshot":
            self.send_json(mc.get_snapshot())
            return

        if path == "/api/mc/trends":
            self.send_json(mc.get_usage_trends())
            return

        if path == "/api/agents/engines":
            self.send_json(runner.get_available_engines(load_config()))
            return

        if path == "/api/agents/runs":
            self.send_json({"runs": runner.list_runs(), "engines": runner.get_available_engines(load_config())})
            return

        if path.startswith("/api/agents/runs/"):
            rid = path.rsplit("/", 1)[-1]
            r = runner.get_run(rid)
            if r:
                self.send_json(r)
            else:
                self.send_json({"error": "Run not found"}, code=404)
            return

        if path.startswith("/api/mc/approvals/"):
            appr_id_str = path.rsplit("/", 1)[-1]
            if appr_id_str.isdigit():
                appr = mc.get_approval(int(appr_id_str))
                if appr:
                    self.send_json(appr)
                else:
                    self.send_json({"error": "Approval not found"}, code=404)
                return

        if path == "/api/config":
            cfg = load_config()
            safe_cfg = json.loads(json.dumps(cfg))
            volc_cfg = safe_cfg.setdefault("volcengine", {})
            for secret_key in ("api_key", "ak", "sk"):
                raw_val = volc_cfg.pop(secret_key, "")
                volc_cfg[f"{secret_key}_configured"] = bool(raw_val and str(raw_val).strip())
                volc_cfg[f"{secret_key}_masked"] = _mask_secret(raw_val)
            wb_cfg = safe_cfg.setdefault("workbuddy", {})
            for secret_key in ("token", "cookie"):
                raw_val = wb_cfg.pop(secret_key, "")
                wb_cfg[f"{secret_key}_configured"] = bool(raw_val and str(raw_val).strip())
                wb_cfg[f"{secret_key}_masked"] = _mask_secret(raw_val)
            self.send_json(safe_cfg)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self.send_json({"success": False, "message": "无效的 Content-Length"}, code=400)
            return
        if content_len < 0 or content_len > 1024 * 1024:
            self.send_json({"success": False, "message": "请求体过大或无效"}, code=413)
            return
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            req_json = json.loads(body.decode("utf-8", errors="replace")) if body else {}
            if not isinstance(req_json, dict):
                req_json = {}
        except Exception:
            req_json = {}

        # 1. 触发手动签到
        if path == "/api/checkin/run":
            cfg = load_config()
            wb_cfg = cfg.get("workbuddy", {})
            force = req_json.get("force", True)
            res = run_workbuddy_checkin(wb_cfg, force=force)
            update_all_status(notify=True)
            self.send_json(res)
            return

        # 2. 更新配置
        if path == "/api/config/update":
            cfg = load_config()
            if isinstance(req_json.get("volcengine"), dict):
                cfg.setdefault("volcengine", {}).update(req_json["volcengine"])
            if isinstance(req_json.get("workbuddy"), dict):
                wb_update = dict(req_json["workbuddy"])
                if "checkin_time" in wb_update and not _is_valid_hhmm(wb_update["checkin_time"]):
                    self.send_json({"success": False, "message": "签到时间格式错误，请使用 HH:MM（如 09:00）"}, code=400)
                    return
                cfg.setdefault("workbuddy", {}).update(wb_update)
            if isinstance(req_json.get("server"), dict):
                cfg.setdefault("server", {}).update(req_json["server"])
            ok = save_config(cfg)
            update_all_status(notify=True)
            self.send_json({"success": ok, "message": "配置更新成功" if ok else "保存失败"})
            return

        # 3. AG-UI 人机审批决策响应 (Human-in-the-Loop Resolution)
        if path == "/api/circuit_breaker/resolve":
            action = str(req_json.get("action", "ignore"))
            with STATUS_LOCK:
                CIRCUIT_BREAKER["triggered"] = False
                CIRCUIT_BREAKER["resolution"] = action
                CIRCUIT_BREAKER["paused"] = ("pause" in action)
                # 冷却 30 分钟，防止高水位下 2 秒后重复弹窗
                CIRCUIT_BREAKER["dismissed_until"] = time.time() + 1800
            if "switch" in action:
                msg = "已确认熔断决策：系统已将后续任务导流至高阶备用模型池 (Claude 3.5 Sonnet / Pro)"
            elif "pause" in action:
                msg = "已确认熔断决策：后台自动化任务已进入挂起保底状态，等待到期窗口重置"
            else:
                msg = "已确认风险放行，保持现状并强制继续使用当前模型（30分钟内不再重复拦截）"
            
            EVENT_HUB.broadcast_event("CIRCUIT_BREAKER_RESOLVED", {"action": action, "message": msg})
            update_all_status(notify=True)
            self.send_json({"success": True, "message": msg})
            return

        # 4. 模拟测试 90% 熔断拦截 (方便用户即时测试体验)
        if path == "/api/circuit_breaker/test":
            with STATUS_LOCK:
                CIRCUIT_BREAKER["triggered"] = True
                CIRCUIT_BREAKER["agent"] = "Google Antigravity (模拟演练)"
                CIRCUIT_BREAKER["current_usage"] = 92.4
                CIRCUIT_BREAKER["message"] = "【演练测试】Antigravity 5小时配额消耗已达 92.4% (超过 90% 警戒线)！即将触发官方限流。"
                CIRCUIT_BREAKER["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                cb_snapshot = dict(CIRCUIT_BREAKER)
            EVENT_HUB.broadcast_event("HUMAN_INTERACTION_REQUIRED", cb_snapshot)
            self.send_json({"success": True, "message": "90% 熔断审批卡片已推送到前端界面！"})
            return

        # 4.5 Mission Control APIs (多 Agent 任务与审批治理)
        if path == "/api/mc/tasks":
            try:
                task = mc.create_task(
                    title=req_json.get("title", ""),
                    agent=req_json.get("agent", "antigravity"),
                    status=req_json.get("status", "queued"),
                    priority=req_json.get("priority", "normal"),
                    summary=req_json.get("summary", ""),
                    source=req_json.get("source", "manual"),
                )
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                self.send_json({"success": True, "task": task})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/mc/tasks/update":
            try:
                task = mc.update_task(
                    task_id=req_json.get("id"),
                    status=req_json.get("status"),
                    summary=req_json.get("summary"),
                    priority=req_json.get("priority"),
                )
                if not task:
                    self.send_json({"success": False, "message": "任务不存在"}, code=404)
                    return
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                self.send_json({"success": True, "task": task})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/mc/tasks/delete":
            try:
                ok = mc.delete_task(req_json.get("id"))
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                self.send_json({"success": ok})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/mc/approvals":
            try:
                appr = mc.create_approval(
                    title=req_json.get("title", ""),
                    agent=req_json.get("agent", "codex"),
                    action_preview=req_json.get("action_preview", ""),
                    risk_level=req_json.get("risk_level", "high"),
                    task_id=req_json.get("task_id"),
                )
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                send_macos_notification(
                    f"🛡️ 待审批 [{appr['risk_level'].upper()}]",
                    f"{appr['agent'].upper()}: {appr['title']}",
                    subtitle="Mission Control 人工门控",
                )
                self.send_json({"success": True, "approval": appr})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/mc/approvals/resolve":
            try:
                appr = mc.resolve_approval(
                    approval_id=req_json.get("id"),
                    decision=req_json.get("decision", "approved"),
                    note=req_json.get("note", ""),
                )
                if not appr:
                    self.send_json({"success": False, "message": "审批单不存在"}, code=404)
                    return
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                self.send_json({"success": True, "approval": appr})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/mc/approvals/test":
            try:
                task = mc.create_task(
                    title="推送生产分支变更并执行数据库迁移",
                    agent="codex",
                    status="waiting_approval",
                    priority="high",
                    summary="Codex 已生成迁移脚本，等待人工审批高危执行命令",
                    source="demo",
                )
                appr = mc.create_approval(
                    title="执行 git push origin main && alembic upgrade head",
                    agent="codex",
                    action_preview="git push origin main\nalembic upgrade head --sql=false",
                    risk_level="high",
                    task_id=task["id"],
                )
                snap = mc.get_snapshot()
                with STATUS_LOCK:
                    LATEST_STATUS["mission_control"] = snap
                EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                send_macos_notification(
                    "🛡️ 待审批 [HIGH]",
                    f"CODEX: {appr['title']}",
                    subtitle="Mission Control 演练",
                )
                self.send_json({"success": True, "approval": appr, "task": task})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        # 4.6 Unified Multi-Agent Dispatch & Execution APIs (coder/agentapi style)
        if path == "/api/agents/dispatch":
            try:
                cfg = load_config()
                def _on_run_update():
                    snap = mc.get_snapshot()
                    with STATUS_LOCK:
                        LATEST_STATUS["mission_control"] = snap
                    EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                    EVENT_HUB.broadcast_event("AGENT_RUN_UPDATED", {"runs": runner.list_runs()})

                run_rec = runner.dispatch_task(
                    agent=req_json.get("agent", "antigravity"),
                    prompt=req_json.get("prompt", ""),
                    title=req_json.get("title"),
                    cwd=req_json.get("cwd"),
                    priority=req_json.get("priority", "normal"),
                    config=cfg,
                    on_update=_on_run_update,
                    on_notify=lambda t, m: send_macos_notification(t, m, subtitle="多 Agent 调度执行"),
                )
                self.send_json({"success": True, "run": run_rec})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        if path == "/api/agents/runs/cancel":
            try:
                def _on_cancel_update():
                    snap = mc.get_snapshot()
                    with STATUS_LOCK:
                        LATEST_STATUS["mission_control"] = snap
                    EVENT_HUB.broadcast_event("MISSION_CONTROL_UPDATED", snap)
                    EVENT_HUB.broadcast_event("AGENT_RUN_UPDATED", {"runs": runner.list_runs()})
                ok = runner.cancel_run(req_json.get("id", ""), on_update=_on_cancel_update)
                self.send_json({"success": ok, "message": "已中止运行任务" if ok else "任务未在运行或不存在"})
            except Exception as e:
                self.send_json({"success": False, "message": str(e)}, code=400)
            return

        # 5. AG-UI 智能体流式对话引擎 (Agent Chat & Command Streaming)
        if path == "/api/agent/chat":
            agent_id = str(req_json.get("agent", "antigravity"))
            message = str(req_json.get("message", "")).strip()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            def send_stream_event(ev_name, p):
                raw = f"event: {ev_name}\ndata: {json.dumps(p, ensure_ascii=False)}\n\n".encode("utf-8")
                self.wfile.write(raw)
                self.wfile.flush()

            try:
                send_stream_event("RUN_STARTED", {"agent": agent_id, "prompt": message})
                time.sleep(0.1)

                # 智能体工具编排与流式吐字
                answer_parts = []
                if "签到" in message or "打卡" in message:
                    send_stream_event("TOOL_CALL_START", {"tool": "workbuddy_auto_checkin", "args": {}})
                    time.sleep(0.3)
                    cfg = load_config()
                    ck_res = run_workbuddy_checkin(cfg.get("workbuddy", {}), force=True)
                    update_all_status(notify=True)
                    send_stream_event("TOOL_CALL_END", {"tool": "workbuddy_auto_checkin", "result": ck_res.get("message")})
                    rec = ck_res.get("record") or ck_res.get("last_record") or {}
                    answer_parts = [
                        "收到您的指令，已为您触发 WorkBuddy 自动化打卡任务。\n",
                        f"👉 **执行结果**：{ck_res.get('message')}\n",
                        f"当前打卡连续天数：**{rec.get('consecutive_days', 0)} 天**，最新积分余额已同步更新至驾驶舱！"
                    ]
                elif any(k in message for k in ["日报", "体检", "报告", "简报", "概览", "总览"]):
                    send_stream_event("TOOL_CALL_START", {"tool": "generate_agent_cockpit_report", "args": {"scope": "all_agents"}})
                    time.sleep(0.3)
                    cfg = load_config()
                    ag_s = get_antigravity_status()
                    cdx_s = get_codex_status()
                    wb_s = get_workbuddy_status(cfg.get("workbuddy", {}))
                    volc_s = get_volcengine_plan_status(cfg.get("volcengine", {}))
                    send_stream_event("TOOL_CALL_END", {"tool": "generate_agent_cockpit_report", "result": "四大智能体状态数据全量汇总完成"})
                    
                    ag_pct = ag_s.get("quota", {}).get("five_hour_usage", {}).get("percent", 0)
                    cdx_rem = cdx_s.get("five_hour_usage", {}).get("remaining_events", 2500)
                    wb_pts = wb_s.get("total_points", 0)
                    wb_checked = "✅ 已打卡" if wb_s.get("today_checked_in") else "⏳ 未打卡"
                    volc_lat = f"{volc_s.get('latency_ms')}ms" if (volc_s.get("healthy") and volc_s.get("latency_ms") is not None) else "待连接"
                    dual_list = ag_s.get("quota", {}).get("dual_models") or []
                    gemini_status = dual_list[0].get("status", "充裕") if len(dual_list) > 0 else "充裕"
                    claude_status = dual_list[1].get("status", "就绪") if len(dual_list) > 1 else "就绪"
                    with STATUS_LOCK:
                        cb_threshold = CIRCUIT_BREAKER["threshold"]
                        cb_triggered = CIRCUIT_BREAKER["triggered"]
                    if cb_triggered or ag_pct >= cb_threshold:
                        cb_summary = f"⚠️ 当前已触发或超过 **{cb_threshold}%** 警戒线（Antigravity 5h 已用 {ag_pct}%），建议及时人工介入处置。"
                    else:
                        cb_summary = f"当前警戒线为 **{cb_threshold}%**，Antigravity 处于绿色安全水位，无需人工干预。"
                    
                    answer_parts = [
                        "📋 **Agent Cockpit 多智能体实时运行与用量综合体检日报**\n\n",
                        f"📅 **生成时间**：{time.strftime('%Y-%m-%d %H:%M:%S')} · 运行协议：AG-UI Protocol 1.0\n\n",
                        "### 📊 核心智能体用量汇总：\n",
                        f"1. **⚡ Google Antigravity**\n",
                        f"   - 订阅与数据源：`{ag_s.get('user_tier', 'Google AI Pro')}` ({ag_s.get('data_source', '官方直连')})\n",
                        f"   - 5小时额度：已用 **{ag_pct}%** (重置倒计时: {ag_s.get('quota', {}).get('five_hour_usage', {}).get('reset_countdown_human', '随时就绪')})\n",
                        f"   - 双模型池状态：主力 Gemini ({gemini_status}) · 高阶 Claude ({claude_status})\n",
                        f"   - 缓存省流效益：Prompt 缓存命中率高达 **{ag_s.get('quota', {}).get('tokens', {}).get('cache_savings_ratio', '1.0x')}**\n\n",
                        f"2. **🧠 OpenAI Codex**\n",
                        f"   - 运行状态：{'✅ 执行中' if cdx_s.get('running') else '🟢 就绪 (已安装)'} · 订阅：{cdx_s.get('plan_type', '未知')} ({cdx_s.get('data_source', '')})\n",
                        f"   - 5小时额度：{cdx_s.get('five_hour_usage', {}).get('human_used', '0%')} · 7天周额度：{cdx_s.get('weekly_usage', {}).get('human_used', '0%')}\n",
                        f"   - 重置到期节点：{cdx_s.get('five_hour_usage', {}).get('reset_expire_time', '随时可用')}\n\n",
                        f"3. **🤖 WorkBuddy 腾讯全场景**\n",
                        f"   - 今日签到：**{wb_checked}** · 账户积分余额：**{wb_pts:,}** 积分 (连续 {wb_s.get('consecutive_days', 0)} 天)\n",
                        f"   - 自动防断签：每日 {wb_s.get('checkin_time', '09:00')} 守护线程已激活\n\n",
                        f"4. **🌋 火山引擎 Plan API**\n",
                        f"   - 接口状态：{'🟢 通道畅通' if volc_s.get('healthy') else '⚪ 待配置 Key'} (延迟: {volc_lat})\n",
                        f"   - 套餐到期：{volc_s.get('plan_expire_human', '未设置')}\n",
                        f"   - 5小时/7天/月度配额：{volc_s.get('five_hour_quota', {}).get('percent', 0)}% · {volc_s.get('weekly_quota', {}).get('percent', 0)}% · {volc_s.get('monthly_quota', {}).get('percent', 0)}%\n\n",
                        f"🛡️ **安全熔断评估**：{cb_summary}"
                    ]
                elif "codex" in message.lower() or agent_id == "codex":
                    send_stream_event("TOOL_CALL_START", {"tool": "query_codex_status", "args": {}})
                    time.sleep(0.2)
                    cdx_s = get_codex_status()
                    send_stream_event("TOOL_CALL_END", {"tool": "query_codex_status", "result": f"读取到 {cdx_s.get('total_log_events', 0)} 条本地事件"})
                    c5h = cdx_s.get("five_hour_usage", {})
                    cwk = cdx_s.get("weekly_usage", {})
                    answer_parts = [
                        "已为您查询 **OpenAI Codex** 本地编程智能体指标：\n\n",
                        f"- 📁 **安装环境**：{cdx_s.get('home_dir')} (版本: {cdx_s.get('app_version', '1.0')} · 订阅: {cdx_s.get('plan_type', '未知')})\n",
                        f"- ⏱️ **5小时窗口配额**：{c5h.get('human_used', '0%')} (重置: {c5h.get('reset_countdown_human')} · {c5h.get('reset_expire_time')})\n",
                        f"- 📅 **7天周总配额**：{cwk.get('human_used', '0%')} (重置: {cwk.get('reset_countdown_human')} · {cwk.get('reset_expire_time')})\n",
                        f"- 📊 **本地日志总数**：{cdx_s.get('total_log_events', 0):,} 条 ({cdx_s.get('data_source', '')})"
                    ]
                elif any(k in message.lower() for k in ["火山", "方舟", "volcengine"]) or agent_id == "volcengine":
                    send_stream_event("TOOL_CALL_START", {"tool": "test_volcengine_latency", "args": {}})
                    time.sleep(0.2)
                    volc_s = get_volcengine_plan_status(load_config().get("volcengine", {}))
                    lat_text = f"延迟 {volc_s.get('latency_ms')}ms" if volc_s.get("latency_ms") is not None else volc_s.get("message", "未连接")
                    send_stream_event("TOOL_CALL_END", {"tool": "test_volcengine_latency", "result": lat_text})
                    answer_parts = [
                        "已完成 **火山引擎方舟 Plan API** 通道探测：\n\n",
                        f"- 📡 **通道连通性**：{'🟢 畅通' if volc_s.get('healthy') else '⚠️ 需检查配置'} ({volc_s.get('message', '')})\n",
                        f"- ⚡ **网络往返延迟**：{volc_s.get('latency_ms') if volc_s.get('latency_ms') is not None else '-'} ms\n",
                        f"- 🤖 **绑定预设模型**：`{volc_s.get('model_name')}`\n",
                        f"- 📆 **套餐订阅到期**：{volc_s.get('plan_expire_human', '未设置')}\n",
                        f"- ⏱️ **5小时滑动用量**：{volc_s.get('five_hour_quota', {}).get('human_used', '0%')} (到期: {volc_s.get('five_hour_quota', {}).get('reset_expire_time', '-')})\n",
                        f"- 📅 **7天周配额**：{volc_s.get('weekly_quota', {}).get('human_used', '0%')} ({volc_s.get('weekly_quota', {}).get('percent', 0)}%，重置: {volc_s.get('weekly_quota', {}).get('reset_expire_time', '-')})\n",
                        f"- 🗓️ **月度总额度**：{volc_s.get('monthly_quota', {}).get('human_used', '0%')} ({volc_s.get('monthly_quota', {}).get('percent', 0)}%，重置: {volc_s.get('monthly_quota', {}).get('reset_expire_time', '-')})"
                    ]
                elif "配额" in message or "额度" in message or "用量" in message:
                    send_stream_event("TOOL_CALL_START", {"tool": "query_official_quota", "args": {"target": agent_id}})
                    time.sleep(0.2)
                    ag_stat = get_antigravity_status()
                    q_info = ag_stat.get("quota", {}).get("five_hour_usage", {})
                    ag_pct = q_info.get("percent", 0)
                    send_stream_event("TOOL_CALL_END", {"tool": "query_official_quota", "result": f"{ag_stat.get('data_source', '数据获取成功')}"})
                    warn_text = "🚨 已触碰 90% 熔断阈值，建议立即处理。" if ag_pct >= 90 else "安全（当前未触碰 90% 熔断阈值）。"
                    answer_parts = [
                        f"已为您实时核实 **{ag_stat.get('name')}** 的最新配额状态：\n\n",
                        f"- 👑 **当前订阅**：{ag_stat.get('user_tier', 'Google AI Pro')} ({ag_stat.get('data_source', '')})\n",
                        f"- ⚡ **当前主力模型**：{ag_stat.get('quota', {}).get('current_model')}\n",
                        f"- ⏱️ **5小时滑动用量**：已用 {ag_pct}% (剩余 {q_info.get('remaining_percent', 100)}%)\n",
                        f"- ⏰ **重置到期时间**：{q_info.get('reset_countdown_human')} ({q_info.get('reset_expire_time', '随时可用')})\n",
                        f"- 🛡️ **警戒状态**：{warn_text}"
                    ]
                elif "熔断" in message or "超额" in message:
                    send_stream_event("TOOL_CALL_START", {"tool": "trigger_circuit_breaker_test", "args": {"threshold": 90.0}})
                    time.sleep(0.3)
                    with STATUS_LOCK:
                        CIRCUIT_BREAKER["triggered"] = True
                        CIRCUIT_BREAKER["agent"] = "Google Antigravity"
                        CIRCUIT_BREAKER["current_usage"] = 92.5
                        CIRCUIT_BREAKER["message"] = "【演练测试】Antigravity 5小时额度已达 92.5%，触碰 90% 安全警戒线！已进入 Human-in-the-Loop 人机协同审批流程。"
                        CIRCUIT_BREAKER["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        cb_snapshot = dict(CIRCUIT_BREAKER)
                    EVENT_HUB.broadcast_event("HUMAN_INTERACTION_REQUIRED", cb_snapshot)
                    send_stream_event("TOOL_CALL_END", {"tool": "trigger_circuit_breaker_test", "result": "已成功向全网广播 90% 熔断拦截事件"})
                    answer_parts = [
                        "🚨 **安全熔断已触发！**\n\n",
                        "当前检测到 Google Antigravity 5小时额度消耗已达 **92.5%**（超过预设的 **90%** 警戒线）。\n",
                        "根据 AG-UI 协议规范，后台已触发 **Human-in-the-Loop（人机协同审批）** 机制并弹出紧急决策面板，请在屏幕中央选择处理方案（如切换备用模型或挂起任务）。"
                    ]
                else:
                    # 真实调用选定的 Agent 进行流式对话 (Antigravity agy CLI / 火山引擎方舟 API / Codex / WorkBuddy)
                    send_stream_event("TOOL_CALL_START", {"tool": f"invoke_{agent_id}_agent", "args": {"prompt": message[:80]}})
                    cfg = load_config()
                    streamed_chars = [0]
                    try:
                        def _emit_delta(ch):
                            streamed_chars[0] += len(ch)
                            send_stream_event("TEXT_MESSAGE_CHUNK", {"delta": ch})

                        runner.stream_direct_chat(agent_id, message, cfg, _emit_delta)
                        send_stream_event("TOOL_CALL_END", {"tool": f"invoke_{agent_id}_agent", "result": f"已真实调用 {agent_id.upper()}，返回 {streamed_chars[0]} 字符"})
                        answer_parts = []
                    except Exception as run_err:
                        send_stream_event("TOOL_CALL_END", {"tool": f"invoke_{agent_id}_agent", "result": f"调用失败: {run_err}"})
                        answer_parts = [f"⚠️ 调用 **{agent_id.upper()}** 失败：{run_err}"]

                for part in answer_parts:
                    step = 3
                    for i in range(0, len(part), step):
                        send_stream_event("TEXT_MESSAGE_CHUNK", {"delta": part[i:i + step]})
                        time.sleep(0.01)
                    time.sleep(0.02)

                send_stream_event("RUN_FINISHED", {"status": "success"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                try:
                    send_stream_event("TEXT_MESSAGE_CHUNK", {"delta": f"\n\n⚠️ 指令执行异常: {e}"})
                    send_stream_event("RUN_FINISHED", {"status": "error", "error": str(e)})
                except Exception:
                    pass
            return

        self.send_error(404, "Not Found")

def main():
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 5999)

    scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
    scheduler_thread.start()

    server_address = (host, port)
    try:
        httpd = ThreadedHTTPServer(server_address, CockpitHandler)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"[错误] 端口 {port} 已被占用，正在尝试使用 6000 端口...")
            port = 6000
            httpd = ThreadedHTTPServer((host, port), CockpitHandler)
        else:
            raise e

    print("=" * 60)
    print("🚀 Agent Cockpit - 多智能体统一监控与自动化工作台已启动")
    print("✨ AG-UI 协议全套引擎已激活: 支持实时流、流式对话抽屉、90% 熔断人机协同审批")
    print(f"👉 本地访问地址: http://localhost:{port}")
    print(f"👉 局域网访问:   http://{socket.gethostname()}:{port}")
    print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出] 正在停止服务...")
        httpd.server_close()

if __name__ == "__main__":
    main()
