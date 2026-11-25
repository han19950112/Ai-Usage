"""
Agent Cockpit Monitors Package
Contains monitoring adapters for Antigravity, Codex, Volcengine, and WorkBuddy,
plus a shared short-TTL process table cache to avoid redundant `ps` subprocesses.
"""

import subprocess
import threading
import time

_PS_LOCK = threading.Lock()
_PS_CACHE = {"ts": 0.0, "output": ""}


def get_cached_ps_output(ttl_sec=6.0):
    """Return `ps -axo pid,command` output cached for `ttl_sec` seconds across all monitors."""
    now = time.time()
    with _PS_LOCK:
        if _PS_CACHE["output"] and (now - _PS_CACHE["ts"]) < ttl_sec:
            return _PS_CACHE["output"]
    try:
        out = subprocess.check_output(
            ["ps", "-axo", "pid,command"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        out = ""
    with _PS_LOCK:
        _PS_CACHE["ts"] = time.time()
        _PS_CACHE["output"] = out
    return out
