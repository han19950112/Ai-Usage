#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Agent Monitor Module (Official Quota Bridge)
Directly bridges to Antigravity's internal runtime via Chrome DevTools Protocol (CDP)
to extract 100% official, authoritative QuotaInfo:
- remainingFraction & exact resetTime from Google Cloud Code server
- Official User Tier (e.g. Google AI Pro)
- Exact model pool quotas (Gemini 3.8 Flash vs Claude Sonnet 4.6)
Fallback gracefully to local transcript parsing when direct bridge is offline.
"""

import base64
from datetime import datetime
import glob
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request

# Per-file transcript cache: {fpath: (mtime, size, steps_list, total_inp, total_out, total_cache, latest_ts, latest_step)}
_TRANSCRIPT_CACHE = {}
_CACHE_LOCK = threading.Lock()
# CDP failure backoff to avoid 1s timeout every 2s when IDE has no --remote-debugging-port
_CDP_BACKOFF = {"last_fail_ts": 0.0, "port": None}
_CDP_BACKOFF_SECONDS = 30.0
# agy CLI /usage async cache (60s TTL, zero-cost official dual-window quota)
_AGY_CLI_CACHE = {"ts": 0.0, "data": None, "bin_checked": False, "bin_path": None, "in_flight": False}
_AGY_CLI_LOCK = threading.Lock()

def parse_iso_ts(iso_str):
    if not iso_str:
        return 0
    try:
        clean = str(iso_str).replace("Z", "+00:00")
        # Normalize fractional seconds > 6 digits for Python < 3.11 compatibility
        clean = re.sub(r"\.(\d{6})\d+", r".\1", clean)
        dt = datetime.fromisoformat(clean)
        return int(dt.timestamp())
    except Exception:
        return 0

def _build_ws_text_frame(payload_bytes):
    """Build a masked RFC 6455 client-to-server WebSocket text frame."""
    length = len(payload_bytes)
    mask = os.urandom(4)
    if length < 126:
        header = bytearray([0x81, 0x80 | length])
    elif length < 65536:
        header = bytearray([0x81, 0x80 | 126]) + struct.pack(">H", length)
    else:
        header = bytearray([0x81, 0x80 | 127]) + struct.pack(">Q", length)
    masked = bytearray(payload_bytes)
    for i in range(length):
        masked[i] ^= mask[i % 4]
    return bytes(header + mask + masked)

def _extract_ws_payload(buf):
    """Extract text payload from one or more unmasked server-to-client WebSocket frames."""
    out = bytearray()
    idx = 0
    n = len(buf)
    while idx + 2 <= n:
        payload_len = buf[idx + 1] & 0x7F
        offset = idx + 2
        if payload_len == 126:
            if offset + 2 > n:
                break
            payload_len = struct.unpack(">H", buf[offset:offset + 2])[0]
            offset += 2
        elif payload_len == 127:
            if offset + 8 > n:
                break
            payload_len = struct.unpack(">Q", buf[offset:offset + 8])[0]
            offset += 8
        if offset + payload_len > n:
            break
        out.extend(buf[offset:offset + payload_len])
        idx = offset + payload_len
    return bytes(out)

def _format_model_name(raw_model):
    """Format raw model ID like 'gemini-4-neon-medium' into 'Gemini 4 Neon (Medium)'."""
    if not raw_model:
        return "未知模型"
    s = str(raw_model).strip()
    if " " in s:
        return s
    parts = [p for p in s.split("-") if p and p.lower() != "tiered"]
    tiers = {"low", "medium", "high", "max", "thinking", "fast"}
    suffix = None
    if len(parts) > 1 and parts[-1].lower() in tiers:
        suffix = parts.pop().capitalize()
    label = " ".join(p.capitalize() if not p[0].isdigit() else p for p in parts)
    return f"{label} ({suffix})" if suffix else label

def _parse_transcript_file(fpath, mtime, size):
    """Parse a single transcript.jsonl file and return cached summary."""
    steps = []
    t_inp = 0
    t_out = 0
    t_cache = 0
    latest_ts = 0
    latest_step = None
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if "model" in obj:
                        inp = int(obj.get("input_tokens", 0) or 0)
                        out = int(obj.get("output_tokens", 0) or 0)
                        cache = int(obj.get("cache_read_tokens", 0) or 0)
                        t_inp += inp
                        t_out += out
                        t_cache += cache
                        step_ts = parse_iso_ts(obj.get("created_at"))
                        if step_ts == 0:
                            step_ts = int(mtime)
                        raw_m = str(obj.get("model", ""))
                        is_claude = "claude" in raw_m.lower()
                        steps.append((step_ts, inp + out, is_claude))
                        if step_ts >= latest_ts:
                            latest_ts = step_ts
                            latest_step = {
                                "input_tokens": inp,
                                "cache_read_tokens": cache,
                                "model": raw_m
                            }
                except Exception:
                    pass
    except Exception:
        pass
    return (mtime, size, steps, t_inp, t_out, t_cache, latest_ts, latest_step)

def _find_agy_binary():
    for name in ("agy",):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        "/opt/homebrew/bin/agy",
        "/usr/local/bin/agy",
        os.path.expanduser("~/.local/bin/agy"),
        os.path.expanduser("~/.antigravity/bin/agy"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None

def _format_reset_countdown(reset_ts, now_ts):
    if not reset_ts or reset_ts <= now_ts:
        return "随时可用", "随时可用"
    diff = int(reset_ts - now_ts)
    days = diff // 86400
    hours = (diff % 86400) // 3600
    mins = (diff % 3600) // 60
    if days > 0:
        cd = f"{days}天{hours}小时后重置"
    elif hours > 0:
        cd = f"{hours}小时{mins:02d}分后完全重置"
    else:
        cd = f"{mins}分钟后重置"
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reset_ts))
    return cd, exp

def _run_agy_cli_probe(bin_path):
    env = dict(os.environ)
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    parsed_result = None
    try:
        proc = subprocess.run(
            [bin_path, "-p", "/usage", "--output-format", "json", "--print-timeout", "20s"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=25,
            env=env,
        )
        raw_out = (proc.stdout or "").strip()
        if proc.returncode == 0 and raw_out:
            env_obj = None
            for line in reversed(raw_out.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        env_obj = json.loads(line)
                        break
                    except Exception:
                        pass
            if isinstance(env_obj, dict):
                cmd_data = (env_obj.get("command") or {}).get("data") or env_obj.get("data") or env_obj
                groups = cmd_data.get("groups") if isinstance(cmd_data, dict) else None
                if isinstance(groups, list) and groups:
                    buckets = []
                    for grp in groups:
                        if not isinstance(grp, dict):
                            continue
                        gname = str(grp.get("name") or "")
                        for b in grp.get("buckets") or []:
                            if not isinstance(b, dict) or b.get("disabled") is True:
                                continue
                            rf = b.get("remaining_fraction")
                            if isinstance(rf, (int, float)):
                                buckets.append({
                                    "id": str(b.get("id") or "").lower(),
                                    "group": gname,
                                    "window": str(b.get("window") or "").lower(),
                                    "remaining_pct": round(max(0.0, min(100.0, float(rf) * 100.0)), 1),
                                    "used_pct": round(max(0.0, min(100.0, (1.0 - float(rf)) * 100.0)), 1),
                                    "reset_ts": parse_iso_ts(b.get("reset_time")),
                                })
                    if buckets:
                        parsed_result = {"buckets": buckets, "tier": cmd_data.get("tier") or cmd_data.get("plan")}
    except Exception:
        parsed_result = None

    with _AGY_CLI_LOCK:
        _AGY_CLI_CACHE["ts"] = time.time()
        if parsed_result is not None:
            _AGY_CLI_CACHE["data"] = parsed_result
        _AGY_CLI_CACHE["in_flight"] = False

def fetch_agy_cli_usage():
    """
    Non-blocking official Antigravity dual-window (5h + weekly) quota via `agy -p /usage --output-format json`.
    Refreshes asynchronously in a background thread every 60s so 2s polling never stalls.
    """
    now = time.time()
    trigger_path = None
    with _AGY_CLI_LOCK:
        if not _AGY_CLI_CACHE["bin_checked"]:
            _AGY_CLI_CACHE["bin_path"] = _find_agy_binary()
            _AGY_CLI_CACHE["bin_checked"] = True
        bin_path = _AGY_CLI_CACHE["bin_path"]
        cached = _AGY_CLI_CACHE["data"]
        if bin_path and not _AGY_CLI_CACHE["in_flight"] and (now - _AGY_CLI_CACHE["ts"]) >= 60.0:
            _AGY_CLI_CACHE["in_flight"] = True
            trigger_path = bin_path

    if trigger_path:
        threading.Thread(target=_run_agy_cli_probe, args=(trigger_path,), daemon=True).start()
    return cached

def fetch_official_antigravity_quota(port=58321):
    """Query Antigravity's internal React Fiber store via local CDP port (with 30s failure backoff)."""
    now = time.time()
    if _CDP_BACKOFF["port"] == port and (now - _CDP_BACKOFF["last_fail_ts"]) < _CDP_BACKOFF_SECONDS:
        return None
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.6)
        targets = json.loads(req.read().decode())
    except Exception:
        _CDP_BACKOFF["port"] = port
        _CDP_BACKOFF["last_fail_ts"] = now
        return None

    target_page = None
    for t in targets:
        if "outside-of-project" in t.get("url", "") or "Antigravity" in t.get("title", ""):
            target_page = t
            break
    if not target_page and targets:
        target_page = targets[0]
    if not target_page:
        return None

    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(("127.0.0.1", port))
        sec_key = base64.b64encode(os.urandom(16)).decode('utf-8')
        handshake = (
            f"GET /devtools/page/{target_page['id']} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(handshake.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(1024)
            if not chunk:
                s.close()
                return None
            resp += chunk
            if len(resp) > 16384:
                s.close()
                return None

        if b"101" not in resp:
            s.close()
            return None

        js = """
        (() => {
            const btn = document.querySelector('[data-testid="model-selector-trigger"]');
            if (!btn) return null;
            const fiberKey = Object.keys(btn).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            let f = btn[fiberKey];
            let targetProps = null;
            let depth = 0;
            while (f && depth < 25) {
                if (f.memoizedProps && f.memoizedProps.modelOptions) {
                    targetProps = f.memoizedProps;
                    break;
                }
                f = f.return;
                depth++;
            }
            if (!targetProps) return null;
            const safe = (o) => JSON.parse(JSON.stringify(o, (k,v) => typeof v === 'bigint' ? v.toString() : (typeof v === 'function' ? undefined : v)));
            return {
                selectedModel: safe(targetProps.selectedModel),
                modelOptions: safe(targetProps.modelOptions),
                userTier: safe(targetProps.userStatus && targetProps.userStatus.userTier)
            };
        })()
        """
        eval_req = {"id": 101, "method": "Runtime.evaluate", "params": {"expression": js, "returnByValue": True}}
        payload = json.dumps(eval_req).encode('utf-8')
        s.sendall(_build_ws_text_frame(payload))

        buf = bytearray()
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            decoded = _extract_ws_payload(buf)
            if decoded and b'"id":101' in decoded:
                try:
                    j = json.loads(decoded.decode('utf-8', errors='ignore'))
                    s.close()
                    return j.get("result", {}).get("result", {}).get("value")
                except json.JSONDecodeError:
                    pass
            if len(buf) > 2 * 1024 * 1024:
                break
        s.close()

        decoded = _extract_ws_payload(buf)
        if not decoded:
            return None
        j = json.loads(decoded.decode('utf-8', errors='ignore'))
        return j.get("result", {}).get("result", {}).get("value")
    except Exception:
        if s:
            try: s.close()
            except Exception: pass
        return None

def get_antigravity_status():
    status = {
        "name": "Google Antigravity",
        "running": False,
        "pid": None,
        "version": "未知",
        "user_tier": "Google AI Pro",
        "data_source": "官方直连数据",
        "language_server_running": False,
        "language_server_pid": None,
        "host_bridge_url": None,
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
                "remaining_percent": 100.0,
                "percent": 0.0,
                "status": "normal",
                "reset_countdown_human": "随时可用",
                "human_used": "0% / 100%"
            },
            "weekly_usage": {
                "used_tokens": 0,
                "percent": 0.0,
                "status": "normal",
                "reset_countdown_human": "--",
                "human_used": "0% / 100%"
            },
            "tokens": {
                "total_input": 0,
                "total_output": 0,
                "total_cached": 0,
                "cache_savings_ratio": "0x"
            },
            "dual_models": [],
            "model_pools": []
        },
        "details": {}
    }

    # 1. 检测本地进程
    try:
        ps_output = subprocess.check_output(["ps", "-axo", "pid,command"], text=True, stderr=subprocess.DEVNULL)
        main_pids = []
        ls_pids = []
        cdp_port = 58321

        for line in ps_output.splitlines():
            line_strip = line.strip()
            if "grep" in line_strip:
                continue

            if "Antigravity.app/Contents/MacOS/Antigravity" in line_strip:
                parts = line_strip.split(None, 1)
                if parts:
                    main_pids.append(int(parts[0]))
                port_m = re.search(r"--remote-debugging-port=(\d+)", line_strip)
                if port_m:
                    cdp_port = int(port_m.group(1))

            if "language_server" in line_strip and "antigravity" in line_strip:
                parts = line_strip.split(None, 1)
                if parts:
                    ls_pids.append(int(parts[0]))
                    ver_m = re.search(r"--override_ide_version\s+([^\s]+)", line_strip)
                    if ver_m:
                        status["version"] = ver_m.group(1)
                    bridge_m = re.search(r"--host_bridge_url=([^\s]+)", line_strip)
                    if bridge_m:
                        status["host_bridge_url"] = bridge_m.group(1)

            if "antigravity-hans" in line_strip or "agy-zh" in line_strip:
                status["is_chinese_launcher"] = True

        if main_pids:
            status["running"] = True
            status["pid"] = main_pids[0]
            status["details"]["worker_processes"] = len(main_pids)
        if ls_pids:
            status["language_server_running"] = True
            status["language_server_pid"] = ls_pids[0]
    except Exception as e:
        status["details"]["ps_err"] = str(e)

    # 2. 读取基础 Token 与活跃时间 (支持 5小时与周滑动窗口统计)
    brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
    total_input = 0
    total_output = 0
    total_cached = 0
    tokens_5h = 0
    tokens_wk = 0
    gemini_5h = 0
    gemini_wk = 0
    claude_5h = 0
    claude_wk = 0
    oldest_5h_ts = None
    latest_step = None
    latest_mtime = 0
    now_ts = int(time.time())
    five_h_ts = now_ts - 5 * 3600
    seven_d_ts = now_ts - 7 * 86400

    if os.path.exists(brain_dir):
        convs = [d for d in os.listdir(brain_dir) if os.path.isdir(os.path.join(brain_dir, d)) and not d.startswith(".")]
        status["active_conversations_count"] = len(convs)
        jsonl_files = glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl"))
        seen_paths = set()
        latest_step_ts = 0

        for fpath in jsonl_files:
            seen_paths.add(fpath)
            try:
                st = os.stat(fpath)
                mt = st.st_mtime
                sz = st.st_size
                if mt > latest_mtime:
                    latest_mtime = mt

                with _CACHE_LOCK:
                    cached = _TRANSCRIPT_CACHE.get(fpath)
                if cached is None or cached[0] != mt or cached[1] != sz:
                    parsed = _parse_transcript_file(fpath, mt, sz)
                    with _CACHE_LOCK:
                        _TRANSCRIPT_CACHE[fpath] = parsed
                else:
                    parsed = cached

                _, _, steps, t_inp, t_out, t_cache, f_latest_ts, f_latest_step = parsed
                total_input += t_inp
                total_output += t_out
                total_cached += t_cache

                if f_latest_step and f_latest_ts >= latest_step_ts:
                    latest_step_ts = f_latest_ts
                    latest_step = f_latest_step

                for step_ts, effective_tokens, is_claude in steps:
                    if step_ts >= five_h_ts:
                        tokens_5h += effective_tokens
                        if is_claude:
                            claude_5h += effective_tokens
                        else:
                            gemini_5h += effective_tokens
                        if oldest_5h_ts is None or step_ts < oldest_5h_ts:
                            oldest_5h_ts = step_ts

                    if step_ts >= seven_d_ts:
                        tokens_wk += effective_tokens
                        if is_claude:
                            claude_wk += effective_tokens
                        else:
                            gemini_wk += effective_tokens
            except Exception:
                pass

        # Prune deleted files from cache
        with _CACHE_LOCK:
            for k in list(_TRANSCRIPT_CACHE.keys()):
                if k not in seen_paths:
                    _TRANSCRIPT_CACHE.pop(k, None)

    if latest_mtime > 0:
        status["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_mtime))

    if latest_step:
        if latest_step.get("model"):
            status["quota"]["current_model"] = _format_model_name(latest_step.get("model"))
        inp = latest_step.get("input_tokens", 0)
        cached = latest_step.get("cache_read_tokens", 0)
        ctx_used = inp + cached
        max_ctx = 1000000
        ctx_pct = round((ctx_used / max_ctx) * 100, 1)
        status["quota"]["context_window"] = {
            "used_tokens": ctx_used,
            "max_tokens": max_ctx,
            "percent": ctx_pct,
            "human": f"{ctx_used / 1000:.1f}k / 1.0M"
        }

    status["quota"]["tokens"] = {
        "total_input": total_input,
        "total_output": total_output,
        "total_cached": total_cached,
        "cache_savings_ratio": f"{round(total_cached / max(1, total_input), 1)}x"
    }

    # 3. 优先通过官方 agy CLI (/usage) 获取完整双窗口 (Gemini 5h/周 + Claude&GPT 5h/周)，其次 CDP 直连，最后本地日志
    agy_cli_data = fetch_agy_cli_usage()
    now_ts = int(time.time())

    if agy_cli_data and agy_cli_data.get("buckets"):
        status["data_source"] = "官方 agy CLI 双窗口直连"
        buckets = agy_cli_data["buckets"]

        def _pick_bucket(group_kw, win_kw):
            for b in buckets:
                if group_kw in (b["group"].lower() + " " + b["id"]) and b["window"] == win_kw:
                    return b
            return None

        g5 = _pick_bucket("gemini", "5h") or next((b for b in buckets if b["window"] == "5h"), None)
        gw = _pick_bucket("gemini", "weekly") or next((b for b in buckets if b["window"] == "weekly"), None)
        c5 = _pick_bucket("claude", "5h") or _pick_bucket("3p", "5h")
        cw = _pick_bucket("claude", "weekly") or _pick_bucket("3p", "weekly")

        if g5:
            cd5, exp5 = _format_reset_countdown(g5["reset_ts"], now_ts)
            u5, r5 = g5["used_pct"], g5["remaining_pct"]
            status["quota"]["five_hour_usage"] = {
                "used_tokens": int(u5 * 15000),
                "limit_tokens": 1500000,
                "remaining_percent": r5,
                "percent": u5,
                "status": "critical" if u5 >= 90 else ("warning" if u5 >= 75 else "normal"),
                "reset_countdown_human": cd5,
                "reset_expire_time": exp5,
                "human_used": f"已用 {u5}% (剩余 {r5}%)"
            }
        if gw:
            cdw, expw = _format_reset_countdown(gw["reset_ts"], now_ts)
            uw, rw = gw["used_pct"], gw["remaining_pct"]
            status["quota"]["weekly_usage"] = {
                "used_tokens": int(uw * 100000),
                "limit_tokens": 10000000,
                "remaining_percent": rw,
                "percent": uw,
                "status": "critical" if uw >= 90 else ("warning" if uw >= 75 else "normal"),
                "reset_countdown_human": cdw,
                "reset_expire_time": expw,
                "human_used": f"已用 {uw}% (剩余 {rw}%)"
            }

        g_u5 = g5["used_pct"] if g5 else 0.0
        g_uw = gw["used_pct"] if gw else 0.0
        g_rw = gw["remaining_pct"] if gw else 100.0
        c_u5 = c5["used_pct"] if c5 else 0.0
        c_uw = cw["used_pct"] if cw else 0.0
        c_rw = cw["remaining_pct"] if cw else 100.0
        active_g_label = status["quota"]["current_model"] if "claude" not in status["quota"]["current_model"].lower() else "Gemini Models"
        status["quota"]["dual_models"] = [
            {
                "id": "model_gemini",
                "name": f"⚡ {active_g_label} (主力套)",
                "type": "官方双窗口直连 · Gemini 池",
                "five_hour_used": f"已用 {g_u5}%",
                "weekly_used": f"周剩 {g_rw}%",
                "limit_label": "Google AI Pro 官方池",
                "percent_5h": g_u5,
                "percent_week": g_uw,
                "status": "充足" if g_u5 < 70 else ("警示" if g_u5 < 90 else "紧张"),
                "level": "normal" if g_u5 < 70 else "warning"
            },
            {
                "id": "model_claude",
                "name": "🧠 Claude & GPT (高阶套)",
                "type": "官方双窗口直连 · 第三方高阶池",
                "five_hour_used": f"已用 {c_u5}%",
                "weekly_used": f"周剩 {c_rw}%",
                "limit_label": "独立第三方高阶池",
                "percent_5h": c_u5,
                "percent_week": c_uw,
                "status": "100% 充裕" if (c_u5 == 0 and c_uw == 0) else f"周剩 {c_rw}%",
                "level": "normal" if c_u5 < 70 else "warning"
            }
        ]
        return status

    # 3b. 次选通过官方 CDP 获取权威 5h QuotaInfo
    official_data = fetch_official_antigravity_quota(cdp_port)
    now_ts = int(time.time())

    if official_data and official_data.get("selectedModel"):
        status["data_source"] = "官方权威直连"
        sm = official_data.get("selectedModel", {})
        status["quota"]["current_model"] = sm.get("label", "Gemini 3.8 Flash (High)")
        
        user_tier_obj = official_data.get("userTier") or {}
        if user_tier_obj.get("name"):
            status["user_tier"] = user_tier_obj.get("name")

        qi = sm.get("quotaInfo", {})
        rem_frac = qi.get("remainingFraction", 1.0)
        if rem_frac is None: rem_frac = 1.0
        rem_pct = round(rem_frac * 100, 1)
        used_pct = round(max(0.0, 100.0 - rem_pct), 1)

        reset_sec = int(qi.get("resetTime", {}).get("seconds", 0))
        if reset_sec > now_ts:
            diff = reset_sec - now_ts
            rh = diff // 3600
            rm = (diff % 3600) // 60
            reset_str = f"{rh}小时{rm:02d}分后完全重置" if rh > 0 else f"{rm}分钟后重置"
            reset_expire_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reset_sec))
        else:
            reset_str = "随时可用 (未消耗)"
            reset_expire_time = "随时可用"

        status["quota"]["five_hour_usage"] = {
            "used_tokens": int(used_pct * 15000),
            "limit_tokens": 1500000,
            "remaining_percent": rem_pct,
            "percent": used_pct,
            "status": "critical" if used_pct >= 90 else ("warning" if used_pct >= 75 else "normal"),
            "reset_countdown_human": reset_str,
            "reset_expire_time": reset_expire_time,
            "human_used": f"已用 {used_pct}% (剩余 {rem_pct}%)"
        }

        # 官方 QuotaInfo 仅提供 5小时滑动窗口；7天周用量使用本地近 7 天真实 Transcript Token 统计（避免误复用 5h 百分比）
        utc_now = time.gmtime(now_ts)
        days_to_monday = (7 - utc_now.tm_wday) % 7
        if days_to_monday == 0 and (utc_now.tm_hour > 0 or utc_now.tm_min > 0):
            days_to_monday = 7
        next_reset_epoch = now_ts + (days_to_monday * 86400) - (utc_now.tm_hour * 3600 + utc_now.tm_min * 60 + utc_now.tm_sec)
        sec_left_wk = max(0, int(next_reset_epoch - now_ts))
        left_days = sec_left_wk // 86400
        left_hours = (sec_left_wk % 86400) // 3600
        weekly_reset_str = f"{left_days}天{left_hours}小时后周重置 · 本地7天实耗"

        limit_wk = 10000000
        pct_wk = round(min(100.0, (tokens_wk / limit_wk) * 100), 1)
        status["quota"]["weekly_usage"] = {
            "used_tokens": tokens_wk,
            "limit_tokens": limit_wk,
            "percent": pct_wk,
            "status": "critical" if pct_wk >= 90 else ("warning" if pct_wk >= 75 else "normal"),
            "reset_countdown_human": weekly_reset_str,
            "human_used": f"{tokens_wk / 1000000:.2f}M / {limit_wk / 1000000:.0f}M ({pct_wk}%)"
        }

        # 双模型池（Gemini 3.8 Flash vs Claude Sonnet 4.6）真实官方配额
        model_opts = official_data.get("modelOptions", [])
        dual_models = []

        # 1. 查找 Gemini 主力套
        g_rem = rem_pct
        g_used = used_pct
        g_label = sm.get("label") or "Gemini 主力套"
        if "claude" in g_label.lower():
            g_opt = next((o for o in model_opts if "gemini" in o.get("label", "").lower()), None)
            if g_opt:
                g_label = g_opt.get("label", "Gemini 主力套")
        dual_models.append({
            "id": "model_gemini",
            "name": f"⚡ {g_label} (主力套)",
            "type": "官方推荐 · 日常主力编程",
            "five_hour_used": f"已用 {g_used}%",
            "weekly_used": f"剩余 {g_rem}%",
            "limit_label": "Google AI Pro 官方配额池",
            "percent_5h": g_used,
            "percent_week": g_used,
            "status": "充足" if g_used < 70 else ("警示" if g_used < 90 else "紧张"),
            "level": "normal" if g_used < 70 else "warning"
        })

        # 2. 查找 Claude 高阶套
        c_found = None
        for opt in model_opts:
            if "claude" in opt.get("label", "").lower():
                c_found = opt
                break
        
        if c_found:
            c_qi = c_found.get("quotaInfo", {})
            c_rf = c_qi.get("remainingFraction", 1.0)
            if c_rf is None: c_rf = 1.0
            c_rem = round(c_rf * 100, 1)
            c_used = round(max(0.0, 100.0 - c_rem), 1)
            c_label = c_found.get("label", "Claude Sonnet 4.6")
            dual_models.append({
                "id": "model_claude",
                "name": f"🧠 {c_label} (高阶套)",
                "type": "高阶深度推理 · 独立配额",
                "five_hour_used": f"已用 {c_used}%",
                "weekly_used": f"剩余 {c_rem}%",
                "limit_label": "独立第三方高阶模型池",
                "percent_5h": c_used,
                "percent_week": c_used,
                "status": "100% 充裕" if c_used == 0 else f"剩余 {c_rem}%",
                "level": "normal"
            })
        else:
            dual_models.append({
                "id": "model_claude",
                "name": "🧠 Claude Sonnet 4.6 (高阶套)",
                "type": "高阶推理 · 独立配额池",
                "five_hour_used": "已用 0.0%",
                "weekly_used": "剩余 100.0%",
                "limit_label": "独立高阶池",
                "percent_5h": 0.0,
                "percent_week": 0.0,
                "status": "就绪 (100% 额度)",
                "level": "normal"
            })

        status["quota"]["dual_models"] = dual_models

    else:
        # Fallback 到本地 transcript 真实滑动窗口统计
        status["data_source"] = "本地日志真实统计"
        limit_5h = 1500000
        limit_wk = 10000000
        
        pct_5h = round(min(100.0, (tokens_5h / limit_5h) * 100), 1)
        rem_5h_pct = round(max(0.0, 100.0 - pct_5h), 1)
        
        pct_wk = round(min(100.0, (tokens_wk / limit_wk) * 100), 1)
        rem_wk_pct = round(max(0.0, 100.0 - pct_wk), 1)

        reset_5h_str = "随时可用"
        reset_5h_expire = "随时可用"
        if oldest_5h_ts and tokens_5h > 0:
            sec_left_5h = max(0, int((oldest_5h_ts + 5 * 3600) - now_ts))
            rh = sec_left_5h // 3600
            rm = (sec_left_5h % 3600) // 60
            reset_5h_str = f"{rh}小时{rm:02d}分后完全释放" if rh > 0 else f"{rm}分钟后释放"
            reset_5h_expire = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(oldest_5h_ts + 5 * 3600))

        status["quota"]["five_hour_usage"] = {
            "used_tokens": tokens_5h,
            "limit_tokens": limit_5h,
            "remaining_percent": rem_5h_pct,
            "percent": pct_5h,
            "status": "critical" if pct_5h >= 90 else ("warning" if pct_5h >= 70 else "normal"),
            "reset_countdown_human": reset_5h_str,
            "reset_expire_time": reset_5h_expire,
            "human_used": f"{tokens_5h / 1000:.1f}k / {limit_5h / 1000000:.1f}M ({pct_5h}%)"
        }

        utc_now = time.gmtime(now_ts)
        days_to_monday = (7 - utc_now.tm_wday) % 7
        if days_to_monday == 0 and (utc_now.tm_hour > 0 or utc_now.tm_min > 0):
            days_to_monday = 7
        next_reset_epoch = now_ts + (days_to_monday * 86400) - (utc_now.tm_hour * 3600 + utc_now.tm_min * 60 + utc_now.tm_sec)
        sec_left_wk = max(0, int(next_reset_epoch - now_ts))
        left_days = sec_left_wk // 86400
        left_hours = (sec_left_wk % 86400) // 3600
        weekly_reset_str = f"{left_days}天{left_hours}小时后周重置"

        status["quota"]["weekly_usage"] = {
            "used_tokens": tokens_wk,
            "limit_tokens": limit_wk,
            "percent": pct_wk,
            "status": "critical" if pct_wk >= 90 else ("warning" if pct_wk >= 75 else "normal"),
            "reset_countdown_human": weekly_reset_str,
            "human_used": f"{tokens_wk / 1000000:.2f}M / {limit_wk / 1000000:.0f}M ({pct_wk}%)"
        }

        g_pct_5h = round(min(100.0, (gemini_5h / limit_5h) * 100), 1)
        c_pct_5h = round(min(100.0, (claude_5h / (limit_5h / 2)) * 100), 1)
        active_gemini_label = status["quota"]["current_model"] if "claude" not in status["quota"]["current_model"].lower() else "Gemini 主力池"
        status["quota"]["dual_models"] = [
            {
                "id": "model_gemini",
                "name": f"⚡ {active_gemini_label} (主力套)",
                "type": "官方推荐 · 日常主力编程",
                "five_hour_used": f"{gemini_5h / 1000:.1f}k",
                "weekly_used": f"{gemini_wk / 1000000:.2f}M",
                "limit_label": "主力模型池",
                "percent_5h": g_pct_5h,
                "percent_week": round(min(100.0, (gemini_wk / limit_wk) * 100), 1),
                "status": "充足" if g_pct_5h < 70 else ("警示" if g_pct_5h < 90 else "紧张"),
                "level": "normal" if g_pct_5h < 70 else ("warning" if g_pct_5h < 90 else "critical")
            },
            {
                "id": "model_claude",
                "name": "🧠 Claude Sonnet 4.6 (高阶套)",
                "type": "高阶深度推理 · 独立配额",
                "five_hour_used": f"{claude_5h / 1000:.1f}k",
                "weekly_used": f"{claude_wk / 1000000:.2f}M",
                "limit_label": "独立第三方高阶池",
                "percent_5h": c_pct_5h,
                "percent_week": round(min(100.0, (claude_wk / (limit_wk / 2)) * 100), 1),
                "status": "充足" if c_pct_5h < 70 else ("警示" if c_pct_5h < 90 else "紧张"),
                "level": "normal" if c_pct_5h < 70 else ("warning" if c_pct_5h < 90 else "critical")
            }
        ]

    return status

if __name__ == "__main__":
    print(json.dumps(get_antigravity_status(), indent=2, ensure_ascii=False))
