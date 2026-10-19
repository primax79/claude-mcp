#!/usr/bin/env python3
"""server.py — Standalone MCP Server for Headless Claude Code CLI Orchestration.

Exposes headless `claude` CLI sessions as non-blocking MCP tools for external
orchestrators (Kilo Code, Claude Code, Codex, CI, ai-orchestration).
Follows SPEC.md v0.2.0 (Option B: detached subprocess with pre-allocated UUID session-id).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import uuid
from typing import Annotated, Any, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("claude-mcp")

# Base directory for task state, logs, and telemetry
DATA_DIR = pathlib.Path(os.environ.get("CLAUDE_MCP_DATA_DIR", "~/.claude-mcp")).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "tasks").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

CLAUDE_PROJECTS_DIR = pathlib.Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# Path & Process Helpers
# ---------------------------------------------------------------------------

def encode_cwd_for_claude_projects(cwd: str) -> str:
    """Map a filesystem directory path to Claude Code's internal project folder name.
    Example: /Users/Alfredo/works/foo -> -Users-Alfredo-works-foo
    """
    resolved = str(pathlib.Path(cwd).resolve())
    sanitized = resolved.replace("/", "-")
    if not sanitized.startswith("-"):
        sanitized = "-" + sanitized
    return sanitized


def get_transcript_path(cwd: str, session_id: str) -> pathlib.Path:
    folder_name = encode_cwd_for_claude_projects(cwd)
    return CLAUDE_PROJECTS_DIR / folder_name / f"{session_id}.jsonl"


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_process_cpu_time(pid: int) -> float:
    """Return cumulative CPU time in seconds for a process, or 0.0 if not available."""
    if not is_pid_alive(pid):
        return 0.0
    try:
        res = subprocess.run(["ps", "-p", str(pid), "-o", "cputime="], capture_output=True, text=True, check=False)
        out = res.stdout.strip()
        if not out:
            return 0.0
        # Format can be [[dd-]hh:]mm:ss or mm:ss.ss
        parts = out.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except Exception:
        pass
    return 0.0


def read_transcript_tail(transcript_path: pathlib.Path, max_bytes: int = 65536) -> dict[str, Any]:
    """Read the tail of a Claude Code project JSONL transcript in strictly read-only mode."""
    info: dict[str, Any] = {
        "exists": transcript_path.is_file(),
        "total_cost_usd": None,
        "latest_event_type": None,
        "latest_assistant_text": None,
        "recent_tool_calls": [],
    }
    if not transcript_path.is_file():
        return info

    try:
        size = transcript_path.stat().st_size
        with open(transcript_path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            chunk = f.read().decode("utf-8", errors="ignore")

        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                evt = json.loads(line)
            except Exception:
                continue

            etype = evt.get("type")
            if info["latest_event_type"] is None and etype:
                info["latest_event_type"] = etype

            if etype == "cost-state" and info["total_cost_usd"] is None:
                info["total_cost_usd"] = evt.get("totalCostUSD")

            if etype == "assistant-message" and info["latest_assistant_text"] is None:
                content = evt.get("content", "")
                if isinstance(content, list):
                    texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                    info["latest_assistant_text"] = " ".join(texts)[:500]
                elif isinstance(content, str):
                    info["latest_assistant_text"] = content[:500]

            if etype == "tool-use" and len(info["recent_tool_calls"]) < 5:
                info["recent_tool_calls"].append(evt.get("toolName") or evt.get("name"))

            if (
                info["total_cost_usd"] is not None
                and info["latest_assistant_text"] is not None
                and len(info["recent_tool_calls"]) > 0
            ):
                break
    except Exception:
        pass
    return info


def save_task_record(task_id: str, record: dict[str, Any]) -> None:
    fpath = DATA_DIR / "tasks" / f"{task_id}.json"
    fpath.write_text(json.dumps(record, indent=2), encoding="utf-8")


def load_task_record(task_id: str) -> dict[str, Any] | None:
    fpath = DATA_DIR / "tasks" / f"{task_id}.json"
    if not fpath.is_file():
        return None
    try:
        return json.loads(fpath.read_text(encoding="utf-8"))
    except Exception:
        return None


def reconcile_task_if_orphaned(record: dict[str, Any]) -> dict[str, Any]:
    """Check whether a running process died and reconcile its state from log files."""
    if record.get("status") not in ("running", "dispatched"):
        return record

    pid = record.get("pid")
    if pid and not is_pid_alive(pid):
        log_file = pathlib.Path(record.get("log_path", ""))
        log_content = log_file.read_text(encoding="utf-8", errors="ignore") if log_file.is_file() else ""
        
        # Check if the process produced valid output before exiting
        if "Outcome:" in log_content or "Final Report" in log_content:
            record["status"] = "completed"
        elif log_content:
            record["status"] = "failed"
            record["error"] = "Process terminated with exit code non-zero or uncaught error"
        else:
            record["status"] = "failed"
            record["error"] = "Process died unexpectedly without producing output"
        record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_task_record(record["task_id"], record)
    return record


# ---------------------------------------------------------------------------
# MCP Tools (11 Tools matching SPEC.md)
# ---------------------------------------------------------------------------

@mcp.tool()
async def claude_implement(
    task_instructions: Annotated[str, Field(description="Instructions for the task.")],
    working_directory: Annotated[str, Field(description="Root directory for the task.")],
    focus_files: Annotated[Optional[list[str]], Field(description="Pinned files the worker must read first.")] = None,
    isolation: Annotated[str, Field(description="Isolation mode: 'none' or 'worktree'.")] = "none",
    branch_name: Annotated[str, Field(description="Branch name seed for worktree isolation.")] = "",
    model: Annotated[str, Field(description="Claude model alias ('sonnet', 'opus', 'haiku') or full model ID.")] = "sonnet",
    effort: Annotated[str, Field(description="Reasoning effort level ('low', 'medium', 'high', 'xhigh', 'max').")] = "medium",
    permission_mode: Annotated[str, Field(description="Permission mode: 'acceptEdits', 'auto', 'bypassPermissions', 'dontAsk', 'plan'.")] = "acceptEdits",
    max_budget_usd: Annotated[Optional[float], Field(description="Maximum dollar budget ceiling for this task.")] = None,
    fallback_model: Annotated[str, Field(description="Fallback model if primary model hits rate limits.")] = "",
    agent: Annotated[str, Field(description="Optional custom Claude agent name (--agent).")] = "",
    allowed_tools: Annotated[Optional[list[str]], Field(description="Whitelist of permitted tool names.")] = None,
    disallowed_tools: Annotated[Optional[list[str]], Field(description="Blacklist of disallowed tool names.")] = None,
    skills_to_load: Annotated[Optional[list[str]], Field(description="List of skill names the worker should activate.")] = None,
    continue_session_id: Annotated[str, Field(description="UUID of a previous session to resume (--resume <id>).")] = "",
    bare: Annotated[bool, Field(description="Pass --bare (disables OAuth credentials; requires ANTHROPIC_API_KEY).")] = False,
    background: Annotated[bool, Field(description="Run non-blocking in background (recommended: true).")] = True,
    timeout_seconds: Annotated[int, Field(description="Timeout ceiling in seconds.")] = 900,
) -> str:
    """Dispatch a coding task to a headless Claude Code CLI session."""
    target_dir = pathlib.Path(working_directory).resolve()
    if not target_dir.is_dir():
        return json.dumps({"error": f"working_directory does not exist: {working_directory}"})

    # Guard B1: --bare disables OAuth and requires ANTHROPIC_API_KEY
    if bare and not os.environ.get("ANTHROPIC_API_KEY"):
        return json.dumps({"error": "bare=True was requested, but ANTHROPIC_API_KEY is not set in the environment."})

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return json.dumps({"error": "claude CLI binary not found on PATH. Please install Claude Code."})

    # Worktree Isolation handling
    worktree_path = None
    actual_workdir = target_dir
    branch = ""

    if isolation == "worktree":
        bname = branch_name or f"claude-{int(datetime.datetime.now().timestamp())}"
        wt_dir = target_dir / ".claude" / "worktrees" / bname
        wt_dir.parent.mkdir(parents=True, exist_ok=True)
        res_wt = subprocess.run(
            ["git", "-C", str(target_dir), "worktree", "add", "-b", bname, str(wt_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res_wt.returncode != 0 and not wt_dir.is_dir():
            return json.dumps({"error": f"Failed to create git worktree: {res_wt.stderr.strip()}"})
        worktree_path = str(wt_dir)
        actual_workdir = wt_dir
        branch = bname

    session_id = continue_session_id or str(uuid.uuid4())
    task_id = f"ctask_{uuid.uuid4().hex[:12]}"
    log_file = DATA_DIR / "logs" / f"{task_id}.log"

    # Assemble prompt with Headless Executor Contract & Focus Files
    prompt_parts = []
    if focus_files:
        ff_str = ", ".join(f"`{f}`" for f in focus_files)
        prompt_parts.append(f"MANDATORY FOCUS FILES: Read these files first before touching any code: {ff_str}.\n")
    if skills_to_load:
        sk_str = ", ".join(skills_to_load)
        prompt_parts.append(f"LOAD SKILLS: Activate skills: {sk_str}.\n")

    prompt_parts.append(
        "RULES: Zero interactivity (never ask questions to the user). "
        "Create 1 atomic commit at completion. "
        "End your message with a structured ## Final Report (Outcome, Files changed, Verification, Issues).\n\n"
        f"TASK INSTRUCTIONS:\n{task_instructions}"
    )
    final_prompt = "".join(prompt_parts)

    cmd = [claude_bin, "-p", final_prompt, "--output-format", "json"]
    if continue_session_id:
        cmd.extend(["--resume", continue_session_id])
    else:
        cmd.extend(["--session-id", session_id])

    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    if permission_mode:
        cmd.extend(["--permission-mode", permission_mode])
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])
    if fallback_model:
        cmd.extend(["--fallback-model", fallback_model])
    if agent:
        cmd.extend(["--agent", agent])
    if allowed_tools:
        cmd.extend(["--allowed-tools", ",".join(allowed_tools)])
    if disallowed_tools:
        cmd.extend(["--disallowed-tools", ",".join(disallowed_tools)])
    if bare:
        cmd.append("--bare")

    # Record initial metadata
    transcript_path = get_transcript_path(str(actual_workdir), session_id)
    record: dict[str, Any] = {
        "task_id": task_id,
        "session_id": session_id,
        "working_directory": str(actual_workdir),
        "base_directory": str(target_dir),
        "worktree_path": worktree_path,
        "branch": branch,
        "log_path": str(log_file),
        "transcript_path": str(transcript_path),
        "model": model,
        "effort": effort,
        "permission_mode": permission_mode,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "dispatched",
        "pid": None,
        "pgid": None,
    }

    if not background:
        # Foreground execution
        proc = subprocess.run(cmd, cwd=str(actual_workdir), capture_output=True, text=True, timeout=timeout_seconds, check=False)
        record["status"] = "completed" if proc.returncode == 0 else "failed"
        record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_file.write_text(proc.stdout + ("\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
        save_task_record(task_id, record)
        return json.dumps({
            "task_id": task_id,
            "session_id": session_id,
            "status": record["status"],
            "stdout": proc.stdout[:2000],
            "worktree_path": worktree_path,
        })

    # Background execution (Option B: detached process group)
    log_fp = open(log_file, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(actual_workdir),
        stdin=subprocess.DEVNULL,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True, # Detached process group for clean killpg
    )
    record["pid"] = proc.pid
    try:
        record["pgid"] = os.getpgid(proc.pid)
    except Exception:
        record["pgid"] = proc.pid
    record["status"] = "running"
    save_task_record(task_id, record)

    return json.dumps({
        "task_id": task_id,
        "session_id": session_id,
        "pid": proc.pid,
        "status": "running",
        "working_directory": str(actual_workdir),
        "worktree_path": worktree_path,
        "branch": branch,
    })


@mcp.tool()
async def claude_task_progress(
    task_id: Annotated[str, Field(description="Task handle returned by claude_implement.")],
) -> str:
    """Inspect the live progress of a running or completed Claude task without locking the session."""
    record = load_task_record(task_id)
    if not record:
        return json.dumps({"error": f"Task {task_id} not found"})

    record = reconcile_task_if_orphaned(record)
    pid = record.get("pid")
    is_alive = is_pid_alive(pid) if pid else False
    cpu_time = get_process_cpu_time(pid) if pid else 0.0

    transcript = read_transcript_tail(pathlib.Path(record.get("transcript_path", "")))

    return json.dumps({
        "task_id": task_id,
        "session_id": record.get("session_id"),
        "status": record.get("status"),
        "is_alive": is_alive,
        "pid": pid,
        "cpu_time_s": cpu_time,
        "cost_usd": transcript.get("total_cost_usd"),
        "latest_event_type": transcript.get("latest_event_type"),
        "latest_assistant_text": transcript.get("latest_assistant_text"),
        "recent_tool_calls": transcript.get("recent_tool_calls"),
        "worktree_path": record.get("worktree_path"),
    })


@mcp.tool()
async def claude_task_wait(
    task_id: Annotated[str, Field(description="Task handle returned by claude_implement.")],
    timeout_seconds: Annotated[Optional[int], Field(description="Timeout ceiling in seconds. None for no timeout.")] = None,
) -> str:
    """Asynchronously wait for a background Claude task to reach a terminal state."""
    start_time = datetime.datetime.now()
    while True:
        record = load_task_record(task_id)
        if not record:
            return json.dumps({"error": f"Task {task_id} not found"})

        record = reconcile_task_if_orphaned(record)
        st = record.get("status")
        if st in ("completed", "failed", "cancelled", "error"):
            return await claude_task_result(task_id)

        if timeout_seconds is not None:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed >= timeout_seconds:
                return json.dumps({
                    "task_id": task_id,
                    "status": "STILL_RUNNING",
                    "elapsed_s": elapsed,
                    "message": f"Task {task_id} is still running after {elapsed:.1f}s",
                })

        await asyncio.sleep(2.0)


@mcp.tool()
async def claude_task_result(
    task_id: Annotated[str, Field(description="Task handle returned by claude_implement.")],
) -> str:
    """Retrieve the final structured result and Final Report of a completed Claude task."""
    record = load_task_record(task_id)
    if not record:
        return json.dumps({"error": f"Task {task_id} not found"})

    record = reconcile_task_if_orphaned(record)
    log_file = pathlib.Path(record.get("log_path", ""))
    output = log_file.read_text(encoding="utf-8", errors="ignore") if log_file.is_file() else ""

    transcript = read_transcript_tail(pathlib.Path(record.get("transcript_path", "")))
    cost_usd = transcript.get("total_cost_usd")

    # Parse Final Report if present
    final_report = None
    fr_m = re.search(r"## Final Report.*", output, re.DOTALL)
    if fr_m:
        final_report = fr_m.group(0).strip()

    # Log telemetry to metrics.jsonl
    telemetry_file = DATA_DIR / "metrics.jsonl"
    with open(telemetry_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "task_id": task_id,
            "session_id": record.get("session_id"),
            "model": record.get("model"),
            "effort": record.get("effort"),
            "status": record.get("status"),
            "cost_usd": cost_usd,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }) + "\n")

    return json.dumps({
        "task_id": task_id,
        "session_id": record.get("session_id"),
        "status": record.get("status"),
        "cost_usd": cost_usd,
        "final_report": final_report,
        "output_tail": output[-2000:] if len(output) > 2000 else output,
        "worktree_path": record.get("worktree_path"),
        "branch": record.get("branch"),
    })


@mcp.tool()
async def claude_task_cancel(
    task_id: Annotated[str, Field(description="Task handle returned by claude_implement.")],
) -> str:
    """Terminate a running Claude task by sending SIGTERM followed by SIGKILL to its process group."""
    record = load_task_record(task_id)
    if not record:
        return json.dumps({"error": f"Task {task_id} not found"})

    pid = record.get("pid")
    pgid = record.get("pgid", pid)

    if pid and is_pid_alive(pid):
        try:
            os.killpg(pgid, signal.SIGTERM)
            await asyncio.sleep(1.0)
            if is_pid_alive(pid):
                os.killpg(pgid, signal.SIGKILL)
        except Exception as e:
            pass

    record["status"] = "cancelled"
    record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_task_record(task_id, record)

    return json.dumps({
        "task_id": task_id,
        "status": "cancelled",
        "session_id": record.get("session_id"),
        "worktree_path": record.get("worktree_path"),
    })


@mcp.tool()
async def claude_task_status() -> str:
    """List all tracked Claude tasks across the server."""
    tasks = []
    task_dir = DATA_DIR / "tasks"
    for jf in sorted(task_dir.glob("*.json")):
        rec = load_task_record(jf.stem)
        if rec:
            rec = reconcile_task_if_orphaned(rec)
            tasks.append({
                "task_id": rec.get("task_id"),
                "status": rec.get("status"),
                "model": rec.get("model"),
                "started_at": rec.get("started_at"),
            })
    return json.dumps({"tasks": tasks, "total": len(tasks)})


@mcp.tool()
async def claude_workspace_status(
    working_directory: Annotated[str, Field(description="Repository path to inspect.")],
) -> str:
    """Inspect git status, current branch, and active worktrees of a workspace."""
    p = pathlib.Path(working_directory).resolve()
    if not p.is_dir():
        return json.dumps({"error": f"Directory not found: {working_directory}"})

    res_st = subprocess.run(["git", "-C", str(p), "status", "--short"], capture_output=True, text=True, check=False)
    res_br = subprocess.run(["git", "-C", str(p), "branch", "--show-current"], capture_output=True, text=True, check=False)
    res_wt = subprocess.run(["git", "-C", str(p), "worktree", "list"], capture_output=True, text=True, check=False)

    return json.dumps({
        "working_directory": str(p),
        "branch": res_br.stdout.strip(),
        "is_clean": not bool(res_st.stdout.strip()),
        "status_short": res_st.stdout.strip(),
        "worktrees": res_wt.stdout.strip().splitlines() if res_wt.stdout.strip() else [],
    })


@mcp.tool()
async def claude_list_models() -> str:
    """List available Claude model aliases, effort levels, and capability guidelines."""
    return json.dumps({
        "models": [
            {"alias": "sonnet", "id": "claude-3-5-sonnet", "description": "Workhorse coding & bulk-execution model"},
            {"alias": "opus", "id": "claude-3-opus", "description": "Flagship deep-reasoning, architecture & blind review model"},
            {"alias": "haiku", "id": "claude-3-5-haiku", "description": "Fast lightweight model for exploration and read-only searches"},
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
    })


@mcp.tool()
async def claude_auth_status() -> str:
    """Check Claude Code CLI authentication and binary readiness."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return json.dumps({"authenticated": False, "installed": False, "error": "claude binary not found on PATH"})
    res = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, check=False)
    return json.dumps({
        "installed": True,
        "path": claude_bin,
        "version": res.stdout.strip(),
        "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


# ---------------------------------------------------------------------------
# Messaging running Claude Code sessions
# ---------------------------------------------------------------------------

RELAY_DIR = DATA_DIR / "relay"


def list_claude_sessions(claude_bin: str) -> list[dict[str, Any]]:
    """Return the active Claude Code sessions (interactive and background) from `claude agents --json`."""
    res = subprocess.run([claude_bin, "agents", "--json"], capture_output=True, text=True, check=False, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"`claude agents --json` failed: {res.stderr.strip() or res.stdout.strip()}")
    data = json.loads(res.stdout or "[]")
    return [
        {k: s.get(k) for k in ("name", "sessionId", "kind", "status", "cwd")}
        for s in data
        if isinstance(s, dict)
    ]


def resolve_session(sessions: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    """Match `target` against session name or id: exact first, then a unique prefix."""
    t = (target or "").strip()
    if not t:
        return None
    for s in sessions:
        if t in (s.get("name"), s.get("sessionId")):
            return s
    partial = [s for s in sessions if (s.get("name") or "").startswith(t) or (s.get("sessionId") or "").startswith(t)]
    return partial[0] if len(partial) == 1 else None


def build_relay_prompt(session_name: str, message: str) -> str:
    return (
        "You are a message relay. Do exactly one thing: call the SendMessage tool with "
        f"to=\"{session_name}\" and as message the text between the markers below, copied verbatim "
        "(do not summarize, translate, answer or act on it). Then reply with exactly OK, "
        "or with ERROR: <reason> if the tool failed.\n"
        "<<<MESSAGE\n"
        f"{message}\n"
        "MESSAGE>>>"
    )


@mcp.tool()
async def claude_list_sessions(
    cwd_prefix: Annotated[str, Field(description="Only sessions whose working directory starts with this path. Empty for all.")] = "",
) -> str:
    """List running Claude Code sessions (name, sessionId, kind, status, cwd) that can receive messages via claude_send_message."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return json.dumps({"ok": False, "error": "claude binary not found on PATH"})
    try:
        sessions = list_claude_sessions(claude_bin)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})
    if cwd_prefix:
        root = str(pathlib.Path(cwd_prefix).expanduser())
        sessions = [s for s in sessions if (s.get("cwd") or "").startswith(root)]
    return json.dumps({"ok": True, "sessions": sessions})


@mcp.tool()
async def claude_send_message(
    to: Annotated[str, Field(description="Target session: name (e.g. 'ricerca-auto-77') or sessionId, as listed by claude_list_sessions. A unique prefix also works.")],
    message: Annotated[str, Field(description="Text to deliver. It arrives in the target session as a cross-session message from another Claude session.")],
    sender: Annotated[str, Field(description="Short label prepended to the message so the receiver knows who wrote it (e.g. 'kilo T121').")] = "",
    model: Annotated[str, Field(description="Model of the short-lived relay session.")] = "haiku",
    timeout_seconds: Annotated[int, Field(description="Maximum seconds for the relay.")] = 180,
) -> str:
    """Send a message to a RUNNING Claude Code session (e.g. the orchestrating architect) and return once it is delivered.

    Delivery goes through a short-lived headless `claude -p` relay that uses Claude Code's built-in
    cross-session SendMessage, so it costs one small model call. Use it for events the receiver must
    act on: a blocking question, a delivered task, a failure. The receiver cannot reply through this
    tool; tell it where to answer (a file, or continue_session_id of your task)."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return json.dumps({"ok": False, "error": "claude binary not found on PATH"})
    if not (message or "").strip():
        return json.dumps({"ok": False, "error": "empty message"})
    try:
        sessions = list_claude_sessions(claude_bin)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})
    target = resolve_session(sessions, to)
    if target is None:
        return json.dumps({
            "ok": False,
            "error": f"no unique running session matches {to!r}",
            "sessions": [s.get("name") for s in sessions],
        })
    text = f"[{sender}] {message}" if sender.strip() else message
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        claude_bin, "-p", build_relay_prompt(target["name"], text),
        "--model", model,
        "--allowedTools", "SendMessage",
    ]
    try:
        # Neutral cwd: the relay must not pick up any project's CLAUDE.md or settings.
        res = await asyncio.to_thread(
            subprocess.run, cmd, cwd=str(RELAY_DIR), capture_output=True, text=True,
            check=False, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": f"relay timed out after {timeout_seconds}s", "to": target["name"]})
    lines = [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    delivered = res.returncode == 0 and last == "OK"
    return json.dumps({
        "ok": delivered,
        "to": target["name"],
        "session_id": target.get("sessionId"),
        "relay_output": last or (res.stderr or "").strip()[-500:],
    })


@mcp.tool()
async def claude_log_issue(
    run_id: Annotated[str, Field(description="Task handle or run identifier.")],
    category: Annotated[str, Field(description="Defect category: specification, tool_failure, drift, test_failure, other.")],
    severity: Annotated[str, Field(description="Severity: low, medium, high, critical.")],
    description: Annotated[str, Field(description="Description of the defect.")],
    files_affected: Annotated[Optional[list[str]], Field(description="List of files involved in the defect.")] = None,
) -> str:
    """Log an observed defect or deviation to issues.jsonl for orchestration telemetry."""
    issue_entry = {
        "run_id": run_id,
        "category": category,
        "severity": severity,
        "description": description,
        "files_affected": files_affected or [],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    issues_file = DATA_DIR / "issues.jsonl"
    with open(issues_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(issue_entry) + "\n")
    return json.dumps({"ok": True, "logged": issue_entry})


@mcp.tool()
async def claude_log_decision(
    branch: Annotated[str, Field(description="Decision branch: 'delegate', 'inline', 'escalate', 'discarded'.")],
    reason: Annotated[str, Field(description="Rationale for the decision.")],
    task_ref: Annotated[str, Field(description="Task ID or spec reference.")] = "",
    followup_needed: Annotated[bool, Field(description="Whether follow-up fixes or reworks were required.")] = False,
    run_id: Annotated[str, Field(description="Associated run ID if applicable.")] = "",
) -> str:
    """Record an architectural decision branch (delegate/inline/escalate/discarded) in decisions.jsonl."""
    if branch not in ("delegate", "inline", "escalate", "discarded"):
        return json.dumps({"error": f"Invalid branch '{branch}'. Must be delegate, inline, escalate, or discarded."})

    dec_entry = {
        "branch": branch,
        "reason": reason,
        "task_ref": task_ref,
        "followup_needed": followup_needed,
        "run_id": run_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    dec_file = DATA_DIR / "decisions.jsonl"
    with open(dec_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(dec_entry) + "\n")
    return json.dumps({"ok": True, "decision": dec_entry})


@mcp.tool()
async def claude_metrics(
    working_directory: Annotated[str, Field(description="Optional filter by working directory.")] = "",
) -> str:
    """Calculate aggregated ROI, cost, turn count, and defect summaries for Claude runs."""
    metrics_file = DATA_DIR / "metrics.jsonl"
    issues_file = DATA_DIR / "issues.jsonl"
    dec_file = DATA_DIR / "decisions.jsonl"

    runs = []
    if metrics_file.is_file():
        for line in metrics_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    runs.append(json.loads(line))
                except Exception:
                    pass

    total_cost = sum(r.get("cost_usd") or 0.0 for r in runs)
    completed_runs = sum(1 for r in runs if r.get("status") == "completed")

    return json.dumps({
        "total_runs": len(runs),
        "completed_runs": completed_runs,
        "total_cost_usd": total_cost,
        "has_issues_log": issues_file.is_file(),
        "has_decisions_log": dec_file.is_file(),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
