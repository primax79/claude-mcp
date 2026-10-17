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

