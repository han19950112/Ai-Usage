#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Cockpit - Unified Multi-Agent Execution & Dispatch Engine
Inspired by coder/agentapi & BloopAI/vibe-kanban:
- Dispatches real prompts/tasks to Antigravity (agy CLI), Volcengine Ark (streaming API),
  OpenAI Codex CLI, and WorkBuddy (codebuddy CLI).
- Tracks running subprocesses, streams live logs, supports cancellation, and syncs
  task lifecycle directly with Mission Control (SQLite WAL).
Zero external dependencies (Python 3 stdlib).
"""

import json
import os
import shutil
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

import mission_control as mc

_RUNS_LOCK = threading.Lock()
_RUNS = {}  # run_id -> dict (metadata + live output buffer)
_PROCS = {}  # run_id -> subprocess.Popen or cancel Event
_MAX_OUTPUT_CHARS = 65536


def generate_batch_id():
    return "batch-" + uuid.uuid4().hex[:8]


def _persist_run_snapshot(run_id):
    with _RUNS_LOCK:
        r = _RUNS.get(run_id)
        snap = dict(r) if r else None
    if snap:
        try:
            mc.save_agent_run(snap)
        except Exception:
            pass


def load_persisted_runs(limit=40):
    try:
        mc.mark_interrupted_runs()
        rows = mc.list_agent_runs(limit=limit)
        with _RUNS_LOCK:
            for row in rows:
                rid = row.get("id")
                if rid and rid not in _RUNS:
                    _RUNS[rid] = row
    except Exception:
        pass


def _find_binary(names, extra_paths=()):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for cand in extra_paths:
        exp = os.path.expanduser(cand)
        if os.path.isfile(exp) and os.access(exp, os.X_OK):
            return exp
    return None


def get_available_engines(config=None):
    config = config or {}
    agy_bin = _find_binary(["agy"], ["/opt/homebrew/bin/agy", "/usr/local/bin/agy", "~/.local/bin/agy"])
    codex_bin = _find_binary(["codex"], ["/opt/homebrew/bin/codex", "/usr/local/bin/codex", "~/.npm-global/bin/codex"])
    wb_bin = _find_binary(
        ["codebuddy", "workbuddy"],
        ["/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy"],
    )
    volc_cfg = config.get("volcengine") or {}
    volc_ready = bool(str(volc_cfg.get("api_key") or "").strip())
    return {
        "antigravity": {"ready": bool(agy_bin), "binary": agy_bin, "mode": "agy CLI (-p)"},
        "volcengine": {"ready": volc_ready, "model": volc_cfg.get("model", "ark-code-latest"), "mode": "Ark Coding Plan Stream API"},
        "codex": {"ready": bool(codex_bin), "binary": codex_bin, "mode": "codex exec CLI"},
        "workbuddy": {"ready": bool(wb_bin), "binary": wb_bin, "mode": "codebuddy CLI"},
    }


def _append_output(run_id, text):
    if not text:
        return
    with _RUNS_LOCK:
        r = _RUNS.get(run_id)
        if not r:
            return
        buf = r["output"] + text
        if len(buf) > _MAX_OUTPUT_CHARS:
            buf = "...[已截断早期日志]...\n" + buf[-_MAX_OUTPUT_CHARS:]
        r["output"] = buf
        r["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def list_runs(limit=40):
    with _RUNS_LOCK:
        items = sorted(_RUNS.values(), key=lambda x: x.get("started_ts", 0), reverse=True)[:limit]
        return [dict(x) for x in items]


def get_run(run_id):
    with _RUNS_LOCK:
        r = _RUNS.get(run_id)
        if r:
            return dict(r)
    return mc.get_agent_run(run_id)


def delete_run(run_id):
    with _RUNS_LOCK:
        r = _RUNS.get(run_id)
        if r and r.get("status") == "running":
            return False
        _RUNS.pop(run_id, None)
    return mc.delete_agent_run(run_id)


def retry_run(run_id, config=None, on_update=None, on_notify=None):
    orig = get_run(run_id)
    if not orig:
        raise ValueError("未找到对应的历史执行记录")
    return dispatch_task(
        agent=orig.get("agent", "antigravity"),
        prompt=orig.get("prompt", ""),
        title=orig.get("title"),
        cwd=orig.get("cwd"),
        priority="normal",
        config=config,
        on_update=on_update,
        on_notify=on_notify,
        batch_id=orig.get("batch_id", ""),
    )


def cancel_run(run_id, on_update=None):
    with _RUNS_LOCK:
        r = _RUNS.get(run_id)
        ctrl = _PROCS.get(run_id)
        if not r or r["status"] != "running":
            return False
        r["status"] = "cancelled"
        r["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        r["output"] += "\n\n[🛑 已由用户手动中止]\n"
        task_id = r.get("task_id")
        agent = r.get("agent", "agent")

    if isinstance(ctrl, subprocess.Popen):
        try:
            ctrl.terminate()
            try:
                ctrl.wait(timeout=2)
            except subprocess.TimeoutExpired:
                ctrl.kill()
        except Exception:
            pass
    elif isinstance(ctrl, threading.Event):
        ctrl.set()

    if task_id:
        mc.update_task(task_id, status="failed", summary="任务已由用户手动中止")
    _persist_run_snapshot(run_id)
    mc.log_activity(agent, "run_cancelled", f"已中止运行任务 {run_id}")
    if on_update:
        on_update()
    return True


def _stream_volcengine_chat(prompt, volc_cfg, on_chunk, cancel_event=None):
    api_key = str(volc_cfg.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置火山引擎 API Key，请在「⚙️ 凭据与设置」中填写")
    base_url = str(volc_cfg.get("base_url") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    if api_key.startswith("ark-") and base_url.endswith("/api/v3"):
        base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
    model = str(volc_cfg.get("model") or "ark-code-latest").strip() or "ark-code-latest"
    if api_key.startswith("ark-") and model == "doubao-seed-evolving":
        model = "ark-code-latest"

    url = f"{base_url}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 Agent Cockpit 调度的专业 AI 工程助手，请简洁、准确地完成任务并输出中文结果。"},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    ctx = ssl.create_default_context()
    if volc_cfg.get("insecure_ssl", False):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=90) as resp:
        for raw_line in resp:
            if cancel_event and cancel_event.is_set():
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                obj = json.loads(data_str)
                choices = obj.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        on_chunk(delta)
            except Exception:
                pass


def _build_cli_command(agent, prompt):
    engines = get_available_engines()
    if agent == "antigravity":
        b = engines["antigravity"]["binary"]
        if not b:
            raise RuntimeError("未检测到 agy CLI，请先安装 Antigravity CLI (~/.local/bin/agy)")
        return [b, "-p", prompt, "--output-format", "text", "--print-timeout", "180s"]
    if agent == "codex":
        b = engines["codex"]["binary"]
        if not b:
            raise RuntimeError("未检测到 codex CLI，可先执行 npm i -g @openai/codex 后即可直接派发任务")
        return [b, "exec", prompt]
    if agent == "workbuddy":
        b = engines["workbuddy"]["binary"]
        if not b:
            raise RuntimeError("未检测到 WorkBuddy / codebuddy CLI")
        return [b, "-p", prompt]
    raise RuntimeError(f"暂不支持的 Agent 执行器: {agent}")


def stream_direct_chat(agent, message, config, on_chunk):
    """Synchronously stream a real reply from the selected agent into on_chunk(delta)."""
    agent = str(agent or "volcengine").strip().lower()
    if agent == "volcengine":
        _stream_volcengine_chat(message, (config or {}).get("volcengine") or {}, on_chunk)
        return

    cmd = _build_cli_command(agent, message)
    env = dict(os.environ)
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        if proc.stdout:
            for line in proc.stdout:
                on_chunk(line)
        proc.wait(timeout=180)
    finally:
        if proc.poll() is None:
            proc.kill()


def dispatch_task(agent, prompt, title=None, cwd=None, priority="normal", config=None, on_update=None, on_notify=None, task_id=None, batch_id=""):
    """Spawn a real background agent run linked to Mission Control and return the run record."""
    agent = str(agent or "antigravity").strip().lower()
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("任务指令 (prompt) 不能为空")
    task_title = (str(title or "").strip() or prompt.splitlines()[0][:70])
    work_dir = os.path.expanduser(str(cwd or "").strip()) if cwd else os.getcwd()
    if not os.path.isdir(work_dir):
        work_dir = os.getcwd()

    if task_id is not None:
        task = mc.update_task(
            task_id,
            status="running",
            summary=f"已派发给 {agent.upper()} 后台执行中 (目录: {work_dir})",
        )
        if not task:
            task = mc.create_task(
                title=task_title,
                agent=agent,
                status="running",
                priority=priority,
                summary=f"已派发给 {agent.upper()} 后台执行中 (目录: {work_dir})",
                source="dispatch",
            )
    else:
        task = mc.create_task(
            title=task_title,
            agent=agent,
            status="running",
            priority=priority,
            summary=f"已派发给 {agent.upper()} 后台执行中 (目录: {work_dir})",
            source="dispatch",
        )
    run_id = "run-" + uuid.uuid4().hex[:8]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    run_rec = {
        "id": run_id,
        "batch_id": str(batch_id or ""),
        "task_id": task["id"],
        "agent": agent,
        "title": task_title,
        "prompt": prompt,
        "cwd": work_dir,
        "status": "running",
        "pid": None,
        "exit_code": None,
        "output": f"[{now_str}] 🚀 正在调度 {agent.upper()} 执行任务...\n工作目录: {work_dir}\n指令: {prompt}\n{'-' * 48}\n",
        "started_ts": time.time(),
        "started_at": now_str,
        "updated_at": now_str,
        "finished_at": "",
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = run_rec
    _persist_run_snapshot(run_id)

    if on_update:
        on_update()

    def _worker():
        exit_code = 0
        final_status = "done"
        err_msg = ""
        try:
            if agent == "volcengine":
                cancel_ev = threading.Event()
                with _RUNS_LOCK:
                    _PROCS[run_id] = cancel_ev
                _stream_volcengine_chat(
                    prompt,
                    (config or {}).get("volcengine") or {},
                    lambda ch: (_append_output(run_id, ch), on_update() if on_update else None),
                    cancel_event=cancel_ev,
                )
                if cancel_ev.is_set():
                    final_status = "cancelled"
            else:
                cmd = _build_cli_command(agent, prompt)
                env = dict(os.environ)
                env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
                proc = subprocess.Popen(
                    cmd,
                    cwd=work_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                with _RUNS_LOCK:
                    _PROCS[run_id] = proc
                    if run_id in _RUNS:
                        _RUNS[run_id]["pid"] = proc.pid
                if on_update:
                    on_update()

                last_emit = 0.0
                last_persist = 0.0
                if proc.stdout:
                    for line in proc.stdout:
                        _append_output(run_id, line)
                        now_t = time.time()
                        if on_update and (now_t - last_emit) >= 0.4:
                            last_emit = now_t
                            on_update()
                        if (now_t - last_persist) >= 2.0:
                            last_persist = now_t
                            _persist_run_snapshot(run_id)
                exit_code = proc.wait(timeout=300)
                with _RUNS_LOCK:
                    cur_st = _RUNS.get(run_id, {}).get("status")
                if cur_st == "cancelled":
                    final_status = "cancelled"
                elif exit_code != 0:
                    final_status = "failed"
                    err_msg = f"进程退出码 {exit_code}"
        except Exception as e:
            final_status = "failed"
            err_msg = str(e)
            _append_output(run_id, f"\n[❌ 执行异常] {err_msg}\n")
        finally:
            fin_str = time.strftime("%Y-%m-%d %H:%M:%S")
            with _RUNS_LOCK:
                _PROCS.pop(run_id, None)
                r = _RUNS.get(run_id)
                if r:
                    if r["status"] != "cancelled":
                        r["status"] = final_status
                    r["exit_code"] = exit_code
                    r["finished_at"] = fin_str
                    r["updated_at"] = fin_str
                    preview = (r["output"].strip().splitlines()[-1] if r["output"].strip() else "")[:140]
                else:
                    preview = ""

            _persist_run_snapshot(run_id)
            if final_status == "done":
                mc.update_task(task["id"], status="done", summary=f"执行完成 · {preview}")
                if on_notify:
                    on_notify(f"✅ {agent.upper()} 任务完成", task_title)
            elif final_status == "failed":
                mc.update_task(task["id"], status="failed", summary=f"执行失败: {err_msg or preview}")
                if on_notify:
                    on_notify(f"❌ {agent.upper()} 任务失败", f"{task_title} ({err_msg})")

            if on_update:
                on_update()

    threading.Thread(target=_worker, daemon=True).start()
    return dict(run_rec)


load_persisted_runs()
