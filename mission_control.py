#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Cockpit - Mission Control Engine (SQLite WAL)
Inspired by builderz-labs/mission-control:
- Multi-Agent Task Board (queued / running / waiting_approval / done / failed)
- Risk-Rated Human-in-the-Loop Approval Queue (low / medium / high / critical)
- Live Local Session Discovery (Antigravity / Codex / WorkBuddy)
- Chronological Activity & Audit Timeline
Zero external dependencies (Python 3 stdlib sqlite3).
"""

import glob
import json
import os
import sqlite3
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.expanduser("~/.agent-cockpit")
if os.path.exists(os.path.join(BASE_DIR, "config.json")):
    DB_PATH = os.path.join(BASE_DIR, "mission_control.db")
else:
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(USER_DATA_DIR, "mission_control.db")

_DB_LOCK = threading.Lock()
_VALID_TASK_STATUSES = ("queued", "running", "waiting_approval", "done", "failed")
_VALID_PRIORITIES = ("low", "normal", "high", "urgent")
_VALID_RISKS = ("low", "medium", "high", "critical")


def _connect():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    agent TEXT NOT NULL DEFAULT 'antigravity',
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    summary TEXT DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    agent TEXT NOT NULL DEFAULT 'codex',
                    title TEXT NOT NULL,
                    action_preview TEXT DEFAULT '',
                    risk_level TEXT NOT NULL DEFAULT 'high',
                    status TEXT NOT NULL DEFAULT 'pending',
                    decision_note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent TEXT NOT NULL DEFAULT 'system',
                    event_type TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    hour TEXT NOT NULL,
                    ag_5h_pct REAL DEFAULT 0,
                    ag_wk_pct REAL DEFAULT 0,
                    ag_tokens_total INTEGER DEFAULT 0,
                    cdx_5h_pct REAL DEFAULT 0,
                    cdx_wk_pct REAL DEFAULT 0,
                    volc_5h_pct REAL DEFAULT 0,
                    volc_wk_pct REAL DEFAULT 0,
                    wb_points REAL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_snapshots_ts ON usage_snapshots(ts);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT DEFAULT '',
                    task_id INTEGER,
                    agent TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    cwd TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    pid INTEGER,
                    exit_code INTEGER,
                    output TEXT DEFAULT '',
                    started_ts REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs(started_ts DESC);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_batch ON agent_runs(batch_id);
            """)
            conn.commit()
        finally:
            conn.close()


def _now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log_activity(agent, event_type, message):
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (str(agent or "system"), str(event_type or "info"), str(message or "")[:500], _now_str()),
            )
            conn.commit()
        finally:
            conn.close()


def create_task(title, agent="antigravity", status="queued", priority="normal", summary="", source="manual"):
    title = str(title or "").strip()
    if not title:
        raise ValueError("任务标题不能为空")
    status = status if status in _VALID_TASK_STATUSES else "queued"
    priority = priority if priority in _VALID_PRIORITIES else "normal"
    agent = str(agent or "antigravity").strip().lower()
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, agent, status, priority, summary, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title[:200], agent, status, priority, str(summary or "")[:1000], str(source or "manual"), now, now),
            )
            task_id = cur.lastrowid
            conn.execute(
                "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (agent, "task_created", f"新建任务 #{task_id}: {title[:80]} [{status}]", now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row)
        finally:
            conn.close()


def update_task(task_id, status=None, summary=None, priority=None):
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            if not row:
                return None
            new_status = status if (status in _VALID_TASK_STATUSES) else row["status"]
            new_summary = str(summary)[:1000] if summary is not None else row["summary"]
            new_priority = priority if (priority in _VALID_PRIORITIES) else row["priority"]
            conn.execute(
                "UPDATE tasks SET status = ?, summary = ?, priority = ?, updated_at = ? WHERE id = ?",
                (new_status, new_summary, new_priority, now, int(task_id)),
            )
            if new_status != row["status"]:
                conn.execute(
                    "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                    (row["agent"], "task_updated", f"任务 #{task_id}「{row['title'][:40]}」状态变更: {row['status']} → {new_status}", now),
                )
            conn.commit()
            updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            return dict(updated)
        finally:
            conn.close()


def delete_task(task_id):
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
            conn.execute(
                "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (row["agent"], "task_deleted", f"已删除任务 #{task_id}: {row['title'][:60]}", now),
            )
            conn.commit()
            return True
        finally:
            conn.close()


def create_approval(title, agent="codex", action_preview="", risk_level="high", task_id=None):
    title = str(title or "").strip()
    if not title:
        raise ValueError("审批标题不能为空")
    risk_level = risk_level if risk_level in _VALID_RISKS else "high"
    agent = str(agent or "codex").strip().lower()
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO approvals (task_id, agent, title, action_preview, risk_level, status, decision_note, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, 'pending', '', ?, '')
                """,
                (int(task_id) if task_id is not None else None, agent, title[:200], str(action_preview or "")[:2000], risk_level, now),
            )
            appr_id = cur.lastrowid
            if task_id is not None:
                conn.execute(
                    "UPDATE tasks SET status = 'waiting_approval', updated_at = ? WHERE id = ?",
                    (now, int(task_id)),
                )
            conn.execute(
                "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (agent, "approval_requested", f"提交待审批 #{appr_id} [{risk_level.upper()}]: {title[:80]}", now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (appr_id,)).fetchone()
            return dict(row)
        finally:
            conn.close()


def get_approval(approval_id):
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (int(approval_id),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def resolve_approval(approval_id, decision, note=""):
    decision = "approved" if str(decision).lower() in ("approve", "approved", "allow", "yes") else "rejected"
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (int(approval_id),)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE approvals SET status = ?, decision_note = ?, resolved_at = ? WHERE id = ?",
                (decision, str(note or "")[:500], now, int(approval_id)),
            )
            if row["task_id"] is not None:
                next_task_status = "running" if decision == "approved" else "failed"
                conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (next_task_status, now, int(row["task_id"])),
                )
            label = "✅ 批准" if decision == "approved" else "❌ 驳回"
            note_suffix = f"（备注: {note[:80]}）" if note else ""
            conn.execute(
                "INSERT INTO activity_logs (agent, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (row["agent"], f"approval_{decision}", f"{label}审批 #{approval_id}「{row['title'][:50]}」{note_suffix}", now),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM approvals WHERE id = ?", (int(approval_id),)).fetchone()
            return dict(updated)
        finally:
            conn.close()


def discover_live_sessions():
    """Auto-discover recent local agent sessions (Antigravity, Codex) without blocking."""
    sessions = []
    now_ts = time.time()

    # 1. Antigravity recent conversations
    brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
    if os.path.isdir(brain_dir):
        try:
            tr_files = glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl"))
            tr_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for fpath in tr_files[:4]:
                mt = os.path.getmtime(fpath)
                conv_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(fpath))))
                age_sec = int(max(0, now_ts - mt))
                active = age_sec < 300
                sessions.append({
                    "agent": "antigravity",
                    "session_id": conv_id[:12],
                    "title": f"Antigravity 会话 {conv_id[:8]}",
                    "status": "running" if active else "idle",
                    "last_active": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt)),
                    "age_human": f"{age_sec // 60}分钟前" if age_sec >= 60 else f"{age_sec}秒前"
                })
        except Exception:
            pass

    # 2. Codex recent sessions
    codex_sess_dir = os.path.expanduser("~/.codex/sessions")
    if os.path.isdir(codex_sess_dir):
        try:
            c_files = glob.glob(os.path.join(codex_sess_dir, "**", "*.jsonl"), recursive=True)
            c_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for fpath in c_files[:4]:
                mt = os.path.getmtime(fpath)
                fname = os.path.basename(fpath)
                age_sec = int(max(0, now_ts - mt))
                active = age_sec < 300
                sessions.append({
                    "agent": "codex",
                    "session_id": fname[-18:-6] if len(fname) > 18 else fname,
                    "title": f"Codex {fname[:22]}",
                    "status": "running" if active else "idle",
                    "last_active": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt)),
                    "age_human": f"{age_sec // 60}分钟前" if age_sec >= 60 else f"{age_sec}秒前"
                })
        except Exception:
            pass

    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return sessions[:8]


def get_snapshot():
    with _DB_LOCK:
        conn = _connect()
        try:
            tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()]
            approvals = [dict(r) for r in conn.execute(
                "SELECT * FROM approvals ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, id DESC LIMIT 60"
            ).fetchall()]
            logs = [dict(r) for r in conn.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 40").fetchall()]
        finally:
            conn.close()

    live_sessions = discover_live_sessions()
    pending_count = sum(1 for a in approvals if a["status"] == "pending")
    running_count = sum(1 for t in tasks if t["status"] == "running")
    waiting_count = sum(1 for t in tasks if t["status"] == "waiting_approval")
    active_sessions_count = sum(1 for s in live_sessions if s["status"] == "running")

    return {
        "summary": {
            "pending_approvals": pending_count,
            "running_tasks": running_count,
            "waiting_tasks": waiting_count,
            "total_tasks": len(tasks),
            "active_sessions": active_sessions_count,
            "total_sessions": len(live_sessions),
        },
        "approvals": approvals,
        "tasks": tasks,
        "live_sessions": live_sessions,
        "activity_logs": logs,
    }


def record_usage_snapshot(status_dict, min_interval_sec=600):
    """Persist a periodic usage snapshot to SQLite WAL (throttled by min_interval_sec)."""
    now_ts = int(time.time())
    day = time.strftime("%Y-%m-%d", time.localtime(now_ts))
    hour = time.strftime("%Y-%m-%d %H:00", time.localtime(now_ts))
    now_str = _now_str()

    ag = status_dict.get("antigravity") or {}
    ag_q = ag.get("quota") or {}
    ag_t = ag_q.get("tokens") or {}
    ag_5h = float((ag_q.get("five_hour_usage") or {}).get("percent") or 0)
    ag_wk = float((ag_q.get("weekly_usage") or {}).get("percent") or 0)
    ag_total = int(ag_t.get("total_input") or 0) + int(ag_t.get("total_output") or 0)

    cdx = status_dict.get("codex") or {}
    cdx_5h = float((cdx.get("five_hour_usage") or {}).get("percent") or 0)
    cdx_wk = float((cdx.get("weekly_usage") or {}).get("percent") or 0)

    volc = status_dict.get("volcengine") or {}
    volc_5h = float((volc.get("five_hour_quota") or {}).get("percent") or 0)
    volc_wk = float((volc.get("weekly_quota") or {}).get("percent") or 0)

    wb = status_dict.get("workbuddy") or {}
    wb_pts = float(wb.get("total_points") or 0)

    with _DB_LOCK:
        conn = _connect()
        try:
            last = conn.execute("SELECT ts FROM usage_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
            if last and (now_ts - int(last["ts"])) < min_interval_sec:
                return False
            conn.execute(
                """
                INSERT INTO usage_snapshots
                (ts, day, hour, ag_5h_pct, ag_wk_pct, ag_tokens_total, cdx_5h_pct, cdx_wk_pct, volc_5h_pct, volc_wk_pct, wb_points, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_ts, day, hour, ag_5h, ag_wk, ag_total, cdx_5h, cdx_wk, volc_5h, volc_wk, wb_pts, now_str),
            )
            # Prune snapshots older than 30 days
            conn.execute("DELETE FROM usage_snapshots WHERE ts < ?", (now_ts - 30 * 86400,))
            conn.commit()
            return True
        finally:
            conn.close()


def _aggregate_local_7d_tokens():
    """Aggregate real daily & per-model tokens from Antigravity transcripts over the last 7 days."""
    from datetime import datetime
    now_ts = int(time.time())
    days_order = [time.strftime("%Y-%m-%d", time.localtime(now_ts - i * 86400)) for i in range(6, -1, -1)]
    daily_map = {d: {"day": d, "input": 0, "output": 0, "cached": 0, "total": 0} for d in days_order}
    model_map = {}

    brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
    if os.path.isdir(brain_dir):
        cutoff = now_ts - 7 * 86400
        for fpath in glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl")):
            try:
                if os.path.getmtime(fpath) < cutoff:
                    continue
                mt = os.path.getmtime(fpath)
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"model"' not in line:
                            continue
                        try:
                            obj = json.loads(line)
                            m = obj.get("model")
                            if not m:
                                continue
                            ts_str = obj.get("created_at") or ""
                            step_ts = 0
                            if ts_str:
                                try:
                                    step_ts = int(datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).timestamp())
                                except Exception:
                                    step_ts = int(mt)
                            else:
                                step_ts = int(mt)
                            if step_ts < cutoff:
                                continue
                            d_key = time.strftime("%Y-%m-%d", time.localtime(step_ts))
                            inp = int(obj.get("input_tokens") or 0)
                            out = int(obj.get("output_tokens") or 0)
                            cache = int(obj.get("cache_read_tokens") or 0)
                            eff = inp + out
                            if d_key in daily_map:
                                daily_map[d_key]["input"] += inp
                                daily_map[d_key]["output"] += out
                                daily_map[d_key]["cached"] += cache
                                daily_map[d_key]["total"] += eff
                            m_str = str(m)
                            if m_str not in model_map:
                                model_map[m_str] = {"model": m_str, "tokens": 0, "cached": 0, "calls": 0}
                            model_map[m_str]["tokens"] += eff
                            model_map[m_str]["cached"] += cache
                            model_map[m_str]["calls"] += 1
                        except Exception:
                            pass
            except Exception:
                pass

    daily_list = [daily_map[d] for d in days_order]
    models_list = sorted(model_map.values(), key=lambda x: x["tokens"], reverse=True)[:8]
    total_7d_tokens = sum(d["total"] for d in daily_list)
    total_7d_cached = sum(d["cached"] for d in daily_list)
    today_tokens = daily_list[-1]["total"] if daily_list else 0
    return {
        "daily_tokens": daily_list,
        "model_breakdown": models_list,
        "total_7d_tokens": total_7d_tokens,
        "total_7d_cached": total_7d_cached,
        "today_tokens": today_tokens,
    }


def get_usage_trends():
    with _DB_LOCK:
        conn = _connect()
        try:
            snaps = [dict(r) for r in conn.execute(
                "SELECT * FROM usage_snapshots ORDER BY ts DESC LIMIT 48"
            ).fetchall()]
        finally:
            conn.close()
    snaps.reverse()
    local_7d = _aggregate_local_7d_tokens()
    return {
        "snapshots": snaps,
        "daily_tokens": local_7d["daily_tokens"],
        "model_breakdown": local_7d["model_breakdown"],
        "summary": {
            "today_tokens": local_7d["today_tokens"],
            "total_7d_tokens": local_7d["total_7d_tokens"],
            "total_7d_cached": local_7d["total_7d_cached"],
            "snapshot_count": len(snaps),
        },
    }


def save_agent_run(run_rec):
    """Upsert an agent execution record into SQLite for persistence across restarts."""
    if not run_rec or not run_rec.get("id"):
        return
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs (
                    id, batch_id, task_id, agent, title, prompt, cwd, status,
                    pid, exit_code, output, started_ts, started_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_rec.get("id")),
                    str(run_rec.get("batch_id") or ""),
                    run_rec.get("task_id"),
                    str(run_rec.get("agent") or "antigravity"),
                    str(run_rec.get("title") or "")[:200],
                    str(run_rec.get("prompt") or "")[:8000],
                    str(run_rec.get("cwd") or "")[:500],
                    str(run_rec.get("status") or "running"),
                    run_rec.get("pid"),
                    run_rec.get("exit_code"),
                    str(run_rec.get("output") or "")[:65536],
                    float(run_rec.get("started_ts") or time.time()),
                    str(run_rec.get("started_at") or _now_str()),
                    str(run_rec.get("updated_at") or _now_str()),
                    str(run_rec.get("finished_at") or ""),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def list_agent_runs(limit=40):
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY started_ts DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_agent_run(run_id):
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (str(run_id),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def delete_agent_run(run_id):
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM agent_runs WHERE id = ?", (str(run_id),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def mark_interrupted_runs():
    """On startup, mark any stale 'running' rows from a prior process as interrupted."""
    now = _now_str()
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT id, output FROM agent_runs WHERE status = 'running'").fetchall()
            for r in rows:
                out = (r["output"] or "") + "\n\n[⚠️ 服务重启，原运行进程已中断]\n"
                conn.execute(
                    "UPDATE agent_runs SET status = 'failed', finished_at = ?, updated_at = ?, output = ? WHERE id = ?",
                    (now, now, out[:65536], r["id"]),
                )
            if rows:
                conn.commit()
        finally:
            conn.close()


init_db()
