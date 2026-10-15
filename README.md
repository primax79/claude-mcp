# claude-mcp

**Standalone MCP Server & Bound Orchestration Skills for Delegating Work to Headless Claude Code CLI Sessions.**

`claude-mcp` is the **Claude Code** execution binding of [`ai-orchestration`](../ai-orchestration/), mirroring [`kilo-mcp`](../kilo-mcp/). It exposes headless `claude` CLI sessions as first-class non-blocking MCP tools so any orchestrator (Kilo Code, Claude Code, a Python orchestration server, or CI) can dispatch implementation or cross-verification tasks to Claude in isolated Git worktrees.

---

## Architecture & Lifecycle

```mermaid
flowchart TB
    ORCH["Orchestrator (Kilo Code / Claude Code / Codex / ai-orchestration UI)"]
    IMPL["1. claude_implement(isolation='worktree', model='sonnet', effort='medium')<br/>Pre-allocates --session-id UUID, creates worktree, spawns detached claude -p"]
    WAIT["2. claude_task_wait(task_id) / claude_task_progress(task_id)<br/>Tails ~/.claude/projects/&lt;encoded-cwd&gt;/&lt;session-id&gt;.jsonl read-only + reconciles PID"]
    RES["3. claude_task_result(task_id)<br/>Parses JSON output, cost_usd, duration, and mandatory ## Final Report"]
    CTRL["4. claude_task_cancel(task_id) / continue_session_id (--resume)<br/>Signals process group (SIGTERM/SIGKILL) or steers existing session"]

    ORCH --> IMPL --> WAIT --> RES --> CTRL
```

## Status & Implementation Tasks

Specification is complete and reviewed ([`SPEC.md`](SPEC.md), [`reviews/001-spec-review-kilo-gemini-3.7-flash.md`](reviews/001-spec-review-kilo-gemini-3.7-flash.md)). Implementation is broken down into 5 atomic tasks in [`tasks/00-INDEX.md`](tasks/00-INDEX.md) and [`tasks/01-claude-mcp-server/plan.md`](tasks/01-claude-mcp-server/plan.md), ready for execution.
