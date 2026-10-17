# 01 - Implement `claude-mcp` Server, Tests & Bound Skills

> **Derived from:** [`../../SPEC.md`](../../SPEC.md) and [`../../reviews/001-spec-review-kilo-gemini-3.7-flash.md`](../../reviews/001-spec-review-kilo-gemini-3.7-flash.md)
> **Reference implementation:** `../../kilo-mcp/server.py` and `../../kilo-mcp/test_server.py`

## Tasks (One Task = One Commit)

### 01.1 - CLI Spike & Project Scaffold (`pyproject.toml`, Config Loader, Transcript Path Helper)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-17)
- **Focus files:** `SPEC.md`, `pyproject.toml`, `claude-mcp.example.toml`, `server.py`

### 01.2 - Detached Subprocess Spawner, Worktree Isolation, `claude_implement` & `claude_task_result`
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-17)
- **Focus files:** `server.py`, `test_server.py`

### 01.3 - Read-Only Tail Transcript Progress (`claude_task_progress`), `claude_task_wait`, `claude_task_cancel` & Orphan Recovery
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-17)
- **Focus files:** `server.py`, `test_server.py`

### 01.4 - Discovery, Workspace & Telemetry Tools (`claude_workspace_status`, `claude_list_models`, `claude_auth_status`, `claude_log_issue`, `claude_log_decision`, `claude_metrics`)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-17)
- **Focus files:** `server.py`, `test_server.py`

### 01.5 - Bound Skills (`claude-mcp-*`), Agent & Marketplace Manifests
- **Profile:** `orchestration`
- **Status:** `done` (2026-10-17)
- **Focus files:** `bindings/*.json`, `scripts/regenerate_bound_skills.py`, `scripts/generate_skill_indices.py`, `plugins/`
