#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Cockpit - Multi-Agent Unified Dashboard & Scheduler Server
Empowered with AG-UI Protocol (Agent-User Interface Protocol 1.0) Real-time Event Streaming.
Zero external dependencies, built purely on Python standard library.
"""

import json
import os
import queue
import socket
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Config] 保存失败: {e}")
        return False

# =========================================================================
# AG-UI Event Hub (Agent-User Interface Protocol 1.0 Event Streaming Engine)
# =========================================================================

class AGUIEventHub:
    """
    Manages active SSE client connections and broadcasts AG-UI standardized events:
    - STATE_SNAPSHOT: Initial state payload upon client connect
    - STATE_DELTA: Partial incremental state patches when usage or quotas update
    - AGENT_TICK: Clock tick and countdown advancement
    - HEARTBEAT: Connection keep-alive
    """
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

EVENT_HUB = AGUIEventHub()

# Global state cache
LATEST_STATUS = {
    "server_time": "",
    "hostname": socket.gethostname(),
    "ag_ui_protocol": "1.0",
    "antigravity": {},
    "codex": {},
    "volcengine": {},
    "workbuddy": {}
}

STATUS_LOCK = threading.Lock()

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
        snapshot = dict(LATEST_STATUS)

    if notify:
        EVENT_HUB.broadcast_event("STATE_DELTA", snapshot)

def background_scheduler():
    """Background scheduler thread for periodic metrics, daily check-ins, and AG-UI event ticks."""
    print("[AG-UI Engine] 智能体实时事件调度线程已就绪 (AG-UI Protocol 1.0)")
    
    # Run once at startup
    update_all_status(notify=False)
    
    # Check if WorkBuddy auto check-in is needed at startup
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

    while True:
        try:
            now_ts = time.time()
            now = time.localtime(now_ts)
            current_time_str = time.strftime("%H:%M", now)
            today_str = time.strftime("%Y-%m-%d", now)
            cfg = load_config()
            target_time = cfg.get("workbuddy", {}).get("checkin_time", "09:00")

            # 1. 每日定时自动打卡检查
            if (current_time_str == target_time and last_day_checked != today_str):
                wb_cfg = cfg.get("workbuddy", {})
                if wb_cfg.get("auto_checkin_enabled", True):
                    print(f"[WorkBuddy] 触发每日定时签到 ({target_time})")
                    res = run_workbuddy_checkin(wb_cfg, force=False)
                    print(f"[WorkBuddy] 定时签到结果: {res.get('message')}")
                    last_day_checked = today_str
                    update_all_status(notify=True)

            # 2. 定时状态轮询与差异广播 (Fast Poll: 2s)
            if now_ts - last_fast_check >= 2.0:
                last_fast_check = now_ts
                ag = get_antigravity_status()
                cdx = get_codex_status()
                wb = get_workbuddy_status(cfg.get("workbuddy", {}))
                
                changed = False
                with STATUS_LOCK:
                    # Check token diff
                    ag_prev = LATEST_STATUS.get("antigravity", {}).get("quota", {}).get("five_hour_usage", {}).get("used_tokens", 0)
                    ag_curr = ag.get("quota", {}).get("five_hour_usage", {}).get("used_tokens", 0)
                    cdx_prev = LATEST_STATUS.get("codex", {}).get("total_log_events", 0)
                    cdx_curr = cdx.get("total_log_events", 0)

                    if ag_prev != ag_curr or cdx_prev != cdx_curr:
                        changed = True

                    LATEST_STATUS["server_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    LATEST_STATUS["antigravity"] = ag
                    LATEST_STATUS["codex"] = cdx
                    LATEST_STATUS["workbuddy"] = wb
                    snapshot = dict(LATEST_STATUS)

                # Push incremental delta update via AG-UI
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
            volc_interval = cfg.get("volcengine", {}).get("check_interval_seconds", 300)
            if now_ts - last_volc_check >= volc_interval:
                update_all_status(notify=True)
                last_volc_check = now_ts

        except Exception as e:
            print(f"[Scheduler Error] {e}")

        time.sleep(1.0)

# =========================================================================
# Multi-threaded HTTP Request Handler with AG-UI SSE Stream Support
# =========================================================================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class CockpitHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 静默常规轮询与流日志，保持终端清爽
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

        # 1. 静态主页
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

        # 2. AG-UI 标准 Server-Sent Events (SSE) 事件通道
        if path in ("/api/events", "/ag-ui/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            client_queue = EVENT_HUB.register_client()
            
            # 立即推送初始状态快照 (STATE_SNAPSHOT)
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
                        # 定时发送注释保活
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                EVENT_HUB.unregister_client(client_queue)
            return

        # 3. 兼容传统 HTTP 状态抓取
        if path == "/api/status":
            with STATUS_LOCK:
                data = dict(LATEST_STATUS)
            self.send_json(data)
            return

        # 4. 配置读取
        if path == "/api/config":
            cfg = load_config()
            safe_cfg = json.loads(json.dumps(cfg))
            if safe_cfg.get("volcengine", {}).get("api_key"):
                k = safe_cfg["volcengine"]["api_key"]
                safe_cfg["volcengine"]["api_key_masked"] = k[:4] + "****" + k[-4:] if len(k) > 8 else "****"
            if safe_cfg.get("workbuddy", {}).get("token"):
                t = safe_cfg["workbuddy"]["token"]
                safe_cfg["workbuddy"]["token_masked"] = t[:4] + "****" + t[-4:] if len(t) > 8 else "****"
            self.send_json(safe_cfg)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            req_json = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except Exception:
            req_json = {}

        if path == "/api/checkin/run":
            cfg = load_config()
            wb_cfg = cfg.get("workbuddy", {})
            force = req_json.get("force", True)
            res = run_workbuddy_checkin(wb_cfg, force=force)
            update_all_status(notify=True)
            self.send_json(res)
            return

        if path == "/api/config/update":
            cfg = load_config()
            if "volcengine" in req_json:
                cfg["volcengine"].update(req_json["volcengine"])
            if "workbuddy" in req_json:
                cfg["workbuddy"].update(req_json["workbuddy"])
            if "server" in req_json:
                cfg["server"].update(req_json["server"])
            
            ok = save_config(cfg)
            update_all_status(notify=True)
            self.send_json({"success": ok, "message": "配置更新成功" if ok else "保存失败"})
            return

        if path == "/api/refresh":
            update_all_status(notify=True)
            self.send_json({"success": True, "message": "状态已强制刷新"})
            return

        self.send_error(404, "Not Found")

def main():
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 5999)

    # Start background scheduler
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
    print("✨ AG-UI 协议引擎已激活: 支持实时 Event Stream (/api/events)")
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
