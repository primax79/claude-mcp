# 01 - Implement `claude-mcp` Server, Tests & Bound Skills

> **Derived from:** [`../../SPEC.md`](../../SPEC.md) and [`../../reviews/001-spec-review-kilo-gemini-3.7-flash.md`](../../reviews/001-spec-review-kilo-gemini-3.7-flash.md)
> **Reference implementation:** `../../kilo-mcp/server.py` and `../../kilo-mcp/test_server.py`

## Tasks (One Task = One Commit)

### 01.1 - CLI Spike & Project Scaffold (`pyproject.toml`, Config Loader, Transcript Path Helper)
- **Profile:** `bulk-execution`
- **Focus files:** `SPEC.md`, `../kilo-mcp/pyproject.toml`, `../kilo-mcp/server.py`
- **Goal:** Scaffold `pyproject.toml` (`mcp`, `tomli`/`tomllib`), `claude-mcp.example.toml`, and core helpers in `server.py` (`DATA_DIR`, `_encode_cwd_for_claude_projects(cwd)` mapping `/Users/foo/bar` → `~/.claude/projects/-Users-foo-bar/<session_id>.jsonl`, `_is_pid_alive`, task record load/save, `--bare` auth guard checking `ANTHROPIC_API_KEY`).
- **Steps:**
  1. Verify real `claude --version` and `claude -p` JSON output structure on this machine (or mock cleanly if offline/no credits).
  2. Create `pyproject.toml`, `claude-mcp.example.toml`, and the foundational helpers in `server.py`.
  3. Write unit tests in `test_server.py` testing path encoding, config loading, and the `bare=True` `ANTHROPIC_API_KEY` guard (finding B1).
- **Verification:** `pytest test_server.py` passes.

### 01.2 - Detached Subprocess Spawner, Worktree Isolation, `claude_implement` & `claude_task_result`
- **Profile:** `deep-reasoning`
- **Focus files:** `server.py`, `test_server.py`, `../kilo-mcp/server.py`
- **Goal:** Implement git worktree creation (`_create_worktree`), detached `claude -p --output-format json --session-id <uuid>` spawning (`start_new_session=True`), `claude_implement` (supporting `model`, `effort`, `permission_mode`, `max_budget_usd`, `fallback_model`, `agent`, `allowed_tools`, `disallowed_tools`, `continue_session_id` via `--resume`), and `claude_task_result`.
- **Verification:** `pytest test_server.py` passes with mocked subprocess tests covering foreground (`background=False`), background (`background=True`), `isolation="worktree"`, and `continue_session_id`.

### 01.3 - Read-Only Tail Transcript Progress (`claude_task_progress`), `claude_task_wait`, `claude_task_cancel` & Orphan Recovery
- **Profile:** `deep-reasoning`
- **Focus files:** `server.py`, `test_server.py`
- **Goal:** Implement `_read_transcript_tail(transcript_path, max_bytes=65536)` (finding B4 & I3: never resume a running session; seek from file end), `_reconcile_task_if_orphaned`, `claude_task_progress`, `claude_task_wait(task_id, timeout_seconds=None)`, `claude_task_cancel` (`os.killpg` SIGTERM → SIGKILL), and `claude_task_status`.
- **Verification:** `pytest test_server.py` passes covering tail parsing on large multi-MB JSONL fixtures, `claude_task_wait` completion/timeout/orphan recovery, and `claude_task_cancel`.

### 01.4 - Discovery, Workspace & Telemetry Tools (`claude_workspace_status`, `claude_list_models`, `claude_auth_status`, `claude_log_issue`, `claude_log_decision`, `claude_metrics`)
- **Profile:** `bulk-execution`
- **Focus files:** `server.py`, `test_server.py`
- **Goal:** Complete the MCP tool surface with workspace git/worktree inspection, model/auth discovery, defect logging (`issues.jsonl`), decision logging (`decisions.jsonl`), and aggregated ROI/decision metrics (`claude_metrics`).
- **Verification:** `pytest test_server.py` passes for all 11 MCP tools.

### 01.5 - Bound Skills (`claude-mcp-*`), Agent & Marketplace Manifests
- **Profile:** `orchestration`
- **Focus files:** `../kilo-mcp/bindings/`, `../kilo-mcp/scripts/regenerate_bound_skills.py`, `../ai-orchestration/scripts/generate_binding.py`
- **Goal:** Create `bindings/{orchestration-methodology,delegation-roi-analysis,conflict-resolver,headless-executor-contract}.json` mapping abstract placeholders to `claude_*` tools, add `scripts/regenerate_bound_skills.py` and `scripts/generate_skill_indices.py`, create `plugins/architect-side/agents/claude-mcp-orchestrator-agent.md`, and add `.claude-plugin/marketplace.json` and `.kilo/marketplace.json`.
- **Verification:** `python3 scripts/regenerate_bound_skills.py && python3 scripts/regenerate_bound_skills.py --check && python3 scripts/generate_skill_indices.py` exits 0.
