"""Unit tests for claude-mcp/server.py."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import pytest
import server


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data" / "tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)


def test_encode_cwd_for_claude_projects():
    encoded = server.encode_cwd_for_claude_projects("/Users/Alfredo/works/ai-coding-tools")
    assert encoded == "-Users-Alfredo-works-ai-coding-tools"


def test_read_transcript_tail(tmp_path: pathlib.Path):
    transcript_file = tmp_path / "test.jsonl"
    lines = [
        json.dumps({"type": "queue-operation", "operation": "enqueue"}),
        json.dumps({"type": "tool-use", "toolName": "Bash"}),
        json.dumps({"type": "assistant-message", "content": [{"type": "text", "text": "Working on feature..."}]}),
        json.dumps({"type": "cost-state", "totalCostUSD": 1.45, "totalAPIDuration": 12000}),
    ]
    transcript_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    info = server.read_transcript_tail(transcript_file)
    assert info["exists"] is True
    assert info["total_cost_usd"] == 1.45
    assert "Working on feature" in info["latest_assistant_text"]
    assert "Bash" in info["recent_tool_calls"]


def test_claude_implement_bare_auth_guard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = asyncio.run(server.claude_implement(
        task_instructions="Test task",
        working_directory=".",
        bare=True,
    ))
    data = json.loads(res)
    assert "error" in data
    assert "ANTHROPIC_API_KEY is not set" in data["error"]


def test_claude_list_models_and_auth():
    models_res = asyncio.run(server.claude_list_models())
    models_data = json.loads(models_res)
    assert len(models_data["models"]) >= 3
    assert "opus" in [m["alias"] for m in models_data["models"]]

    auth_res = asyncio.run(server.claude_auth_status())
    auth_data = json.loads(auth_res)
    assert "installed" in auth_data


def test_claude_log_issue_and_decision():
    issue_res = asyncio.run(server.claude_log_issue(
        run_id="ctask_123",
        category="specification",
        severity="medium",
        description="Missing caller trace",
    ))
    assert json.loads(issue_res)["ok"] is True

    dec_res = asyncio.run(server.claude_log_decision(
        branch="delegate",
        reason="Large multi-file task",
        task_ref="01.1",
    ))
    assert json.loads(dec_res)["ok"] is True

    metrics_res = asyncio.run(server.claude_metrics())
    metrics_data = json.loads(metrics_res)
    assert metrics_data["has_issues_log"] is True
    assert metrics_data["has_decisions_log"] is True


def test_claude_task_status_and_result(tmp_path: pathlib.Path):
    task_id = "ctask_test1"
    log_file = tmp_path / "data" / "logs" / f"{task_id}.log"
    log_file.write_text("All tests pass.\n## Final Report\nOutcome: success\nFiles changed: foo.py", encoding="utf-8")

    record = {
        "task_id": task_id,
        "session_id": "test-uuid",
        "working_directory": str(tmp_path),
        "log_path": str(log_file),
        "transcript_path": str(tmp_path / "nonexistent.jsonl"),
        "status": "completed",
        "started_at": "2026-10-15T12:00:00Z",
    }
    server.save_task_record(task_id, record)

    status_res = asyncio.run(server.claude_task_status())
    status_data = json.loads(status_res)
    assert status_data["total"] >= 1

    res = asyncio.run(server.claude_task_result(task_id))
    res_data = json.loads(res)
    assert res_data["status"] == "completed"
    assert "Final Report" in res_data["final_report"]



SESSIONS_JSON = json.dumps([
    {"name": "ricerca-auto-77", "sessionId": "36234bd2-aaaa", "kind": "interactive", "status": "busy", "cwd": "/Users/x/works/ricerca_auto"},
    {"name": "gcube-audit-f7", "sessionId": "b956c5fe-bbbb", "kind": "interactive", "status": "idle", "cwd": "/Users/x/works/gcube_audit"},
])


class _Res:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _fake_run_factory(calls, relay_stdout="OK\n"):
    def fake_run(cmd, *args, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["agents", "--json"]:
            return _Res(stdout=SESSIONS_JSON)
        return _Res(stdout=relay_stdout)
    return fake_run


def test_resolve_session_exact_and_prefix():
    sessions = json.loads(SESSIONS_JSON)
    assert server.resolve_session(sessions, "ricerca-auto-77")["sessionId"] == "36234bd2-aaaa"
    assert server.resolve_session(sessions, "ricerca-auto-99")["sessionId"] == "36234bd2-aaaa"
    assert server.resolve_session(sessions, "ricerca_auto")["sessionId"] == "36234bd2-aaaa"
    assert server.resolve_session(sessions, "b956c5fe-bbbb")["name"] == "gcube-audit-f7"
    assert server.resolve_session(sessions, "ricerca")["name"] == "ricerca-auto-77"
    assert server.resolve_session(sessions, "nope") is None
    assert server.resolve_session(sessions, "") is None


def test_list_sessions_filters_by_cwd(monkeypatch: pytest.MonkeyPatch):
    calls: list = []
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(server.subprocess, "run", _fake_run_factory(calls))
    out = json.loads(asyncio.run(server.claude_list_sessions(cwd_prefix="/Users/x/works/ricerca_auto")))
    assert out["ok"] is True
    assert [s["name"] for s in out["sessions"]] == ["ricerca-auto-77"]


def test_send_message_runs_relay_with_sender(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    calls: list = []
    monkeypatch.setattr(server, "RELAY_DIR", tmp_path / "relay")
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(server.subprocess, "run", _fake_run_factory(calls))
    out = json.loads(asyncio.run(server.claude_send_message(to="ricerca", message="T121 consegnato", sender="kilo T121")))
    assert out["ok"] is True and out["to"] == "ricerca-auto-77"
    relay_cmd, kwargs = calls[-1]
    assert relay_cmd[1] == "-p"
    assert 'to="ricerca-auto-77"' in relay_cmd[2]
    assert "[kilo T121] T121 consegnato" in relay_cmd[2]
    assert "SendMessage" in relay_cmd[relay_cmd.index("--allowedTools") + 1]
    assert kwargs["cwd"] == str(tmp_path / "relay")


def test_send_message_unknown_target_lists_sessions(monkeypatch: pytest.MonkeyPatch):
    calls: list = []
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(server.subprocess, "run", _fake_run_factory(calls))
    out = json.loads(asyncio.run(server.claude_send_message(to="missing", message="hi")))
    assert out["ok"] is False
    assert "ricerca-auto-77" in out["sessions"]
    assert len(calls) == 1  # no relay spawned


def test_send_message_reports_relay_error(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    calls: list = []
    monkeypatch.setattr(server, "RELAY_DIR", tmp_path / "relay")
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(server.subprocess, "run", _fake_run_factory(calls, relay_stdout="ERROR: session not reachable\n"))
    out = json.loads(asyncio.run(server.claude_send_message(to="ricerca-auto-77", message="hi")))
    assert out["ok"] is False
    assert out["relay_output"].startswith("ERROR")
