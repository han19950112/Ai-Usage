#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Cockpit - Multi-Agent Unified Dashboard & Scheduler Server
Zero external dependencies, built purely on Python standard library.
"""

import json
import os
import socket
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
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

# Global state cache
LATEST_STATUS = {
    "server_time": "",
    "hostname": socket.gethostname(),
    "antigravity": {},
    "codex": {},
    "volcengine": {},
    "workbuddy": {}
}

STATUS_LOCK = threading.Lock()

def update_all_status():
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

def background_scheduler():
    """Background scheduler thread for periodic metrics and daily check-ins."""
    print("[Scheduler] 自动化后台调度线程已启动")
    
    # Run once at startup
    update_all_status()
    
    # Check if WorkBuddy auto check-in is needed at startup
    cfg = load_config()
    wb_cfg = cfg.get("workbuddy", {})
    if wb_cfg.get("auto_checkin_enabled", True) and (wb_cfg.get("token") or wb_cfg.get("cookie") or wb_cfg.get("demo_mode")):
        res = run_workbuddy_checkin(wb_cfg, force=False)
        print(f"[WorkBuddy] 启动自检签到: {res.get('message')}")
        update_all_status()

    last_volc_check = time.time()
    last_day_checked = ""

    while True:
        try:
            cfg = load_config()
            now = time.localtime()
            current_time_str = time.strftime("%H:%M", now)
            today_str = time.strftime("%Y-%m-%d", now)
            target_time = cfg.get("workbuddy", {}).get("checkin_time", "09:00")

            # Check if scheduled time reached today
            if (current_time_str == target_time and last_day_checked != today_str):
                wb_cfg = cfg.get("workbuddy", {})
                if wb_cfg.get("auto_checkin_enabled", True):
                    print(f"[Scheduler] 触发每日定时签到 ({target_time})")
                    res = run_workbuddy_checkin(wb_cfg, force=False)
                    print(f"[WorkBuddy] 定时签到结果: {res.get('message')}")
                    last_day_checked = today_str

            # Update statuses
            volc_interval = cfg.get("volcengine", {}).get("check_interval_seconds", 300)
            if time.time() - last_volc_check >= volc_interval:
                update_all_status()
                last_volc_check = time.time()
            else:
                # Fast refresh local monitors
                ag = get_antigravity_status()
                cdx = get_codex_status()
                wb = get_workbuddy_status(cfg.get("workbuddy", {}))
                with STATUS_LOCK:
                    LATEST_STATUS["server_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    LATEST_STATUS["antigravity"] = ag
                    LATEST_STATUS["codex"] = cdx
                    LATEST_STATUS["workbuddy"] = wb

        except Exception as e:
            print(f"[Scheduler Error] {e}")

        time.sleep(10)

class CockpitHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silent ordinary access logs to keep terminal tidy
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

        if path == "/api/status":
            with STATUS_LOCK:
                data = dict(LATEST_STATUS)
            self.send_json(data)
            return

        if path == "/api/config":
            cfg = load_config()
            # Mask sensitive keys for safety
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
            update_all_status()
            self.send_json(res)
            return

        if path == "/api/config/update":
            cfg = load_config()
            # Update fields
            if "volcengine" in req_json:
                cfg["volcengine"].update(req_json["volcengine"])
            if "workbuddy" in req_json:
                cfg["workbuddy"].update(req_json["workbuddy"])
            if "server" in req_json:
                cfg["server"].update(req_json["server"])
            
            ok = save_config(cfg)
            update_all_status()
            self.send_json({"success": ok, "message": "配置更新成功" if ok else "保存失败"})
            return

        if path == "/api/refresh":
            update_all_status()
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
        httpd = HTTPServer(server_address, CockpitHandler)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"[错误] 端口 {port} 已被占用，正在尝试使用 6000 端口...")
            port = 6000
            httpd = HTTPServer((host, port), CockpitHandler)
        else:
            raise e

    print("=" * 60)
    print("🚀 Agent Cockpit - 多智能体统一监控与自动化工作台已启动")
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
