---
target: SPEC.md
date: 2026-08-19
commit: 8ab63aeea5091827c3e36c1fe90cc341ec79c50d
engine: kilo-gemini-3.7-flash
model: google/gemini-3.7-flash
verdict: proceed with changes
---

# Review: claude-mcp spec round 001 — kilo-gemini-3.7-flash

## 1. Executive Assessment

The core premise of `claude-mcp` is solid and well-motivated: providing a standalone MCP server that allows any orchestrator (Claude Code, Kilo Code, Roo Code, or custom scripts) to delegate coding and refactoring tasks to headless Claude Code CLI sessions, mirroring the proven `kilo-mcp` architect/executor pattern (`claude_implement`, `claude_task_progress`, `claude_task_result`, `claude_task_cancel`).

The spec correctly identifies and accurately references the mechanics of `kilo-mcp` (`_spawn_kilo_background`, `_is_pid_alive`, `_reconcile_task_if_orphaned`, `_create_worktree` in `../kilo-mcp/server.py`).

However, the spec **overclaims** how much of the heavy lifting the Claude CLI handles out of the box for an MCP server, and contains a few dangerous assumptions regarding CLI flag interoperability and state tracking:
1. **Conflicting Execution Modes in Proposed Dispatch**: The spec proposes combining `-p` (`--print`), `--bg` (`--background`), and `--output-format json` in a single command. But in the real Claude CLI, `-p` is foreground synchronous print mode, whereas `--bg` is background daemon mode. Furthermore, several cited flags (`--output-format`, `--max-budget-usd`, `--fallback-model`, `--no-session-persistence`) explicitly note in `--help` that they `(only works with --print)`.
2. **Missing Metadata in `claude agents --json`**: `claude agents --json --all` only outputs coarse session metadata (`id`, `sessionId`, `cwd`, `name`, `state`, `startedAt`), but **omits OS PIDs** for background agents, as well as exit codes, stdout/stderr, failure details, and final output. Relying purely on `claude agents` for cancellation and result collection will break unless `claude-mcp` tracks PIDs and transcripts itself.
3. **Authentication Trap with `--bare`**: The spec recommends `--bare` for clean, isolated dispatch without realizing that `--bare` explicitly disables OAuth and macOS Keychain credential reading, requiring an explicit `ANTHROPIC_API_KEY`.
4. **Conflating Progress Polling with Session Resumption**: Resuming an active background session via `--resume` or `--continue` will cause session conflicts; progress polling must read transcripts or status directly, not resume the session.

Overall, the server will likely need a process-management and transcript-reading layer very similar to `kilo-mcp` (or wrap `-p` in detached subprocesses), rather than being a purely thin passthrough over `claude agents`.

---

## 2. What It Gets Right

1. **Problem Statement and Role Definition (§0, §2)**: Accurately identifies the need for executor flexibility in multi-agent orchestration, positioning Claude Code as an alternative executor alongside Kilo Code.
2. **Accurate Grounding in `kilo-mcp` Internals (§1, §6)**: Correctly models the lifecycles, error modes, and design patterns established in `kilo-mcp` (`server.py`), including PID liveness checking, crash-recovery reconciliation, worktree isolation, and the mandatory Final Report contract.
3. **Real CLI Primitives Identified (§1, §4)**:
   - Successfully identifies `-w` / `--worktree [name]` for native worktree creation.
   - Successfully identifies `--permission-mode <mode>` (`acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`) and `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions`.
   - Successfully identifies `--effort` (`low`, `medium`, `high`, `xhigh`, `max`) and `--model` aliases (`sonnet`, `opus`, `fable`).
   - Accurately locates session transcript persistence under `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.
   - Correctly notes that non-interactive `-p` mode skips workspace trust dialogs and silently ignores invalid settings files.
4. **Phased Spike-First Strategy (§5)**: Pragmatically mandates a manual spike (Phase 1) before implementing any MCP server code, acknowledging that CLI behaviors need experimental verification.

---

## 3. Blocking Findings

### B1. `--bare` Mode Disables OAuth/Keychain and Requires `ANTHROPIC_API_KEY`
- **Location**: SPEC.md §4 (Known gotchas).
- **Issue**: SPEC suggests `--bare` as an opt-in flag for "fully deterministic, no-surprises dispatch". However, running `claude --help` reveals:
  > `--bare Minimal mode: ... Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are never read).`
- **Impact**: Any user or environment authenticated via standard browser/OAuth login (`claude auth login`) will experience immediate authentication failure if `--bare` is passed.
- **Remediation**: Clarify in SPEC.md that `--bare` requires `ANTHROPIC_API_KEY` or `apiKeyHelper` in `--settings`, and cannot be used with standard OAuth/subscription logins.

### B2. Incompatible and Unverified Flag Combinations in Proposed Dispatch (`-p` vs `--bg` vs `--output-format json`)
- **Location**: SPEC.md §3 (`claude_implement` tool definition).
- **Issue**: SPEC proposes dispatching via:
  `claude -p "<task_instructions>" --bg --output-format json [-w <name>] [--model ...] [--effort ...] [--permission-mode ...]`
- **Conflict**:
  1. `claude --help` specifies that `--output-format <format>`, `--max-budget-usd <amount>`, and `--fallback-model <model>` `(only works with --print)`.
  2. `-p` (`--print`) runs a synchronous, foreground process that outputs to stdout and terminates.
  3. `--bg` (`--background`) starts a background agent managed by the `claude agents` daemon.
  4. Passing `-p` together with `--bg` represents two conflicting execution models. If `--bg` is used, `--output-format json` may be ignored or cause errors; if `-p` is used, the process does not return immediately unless spawned in a detached OS process (`setsid`).
- **Remediation**: The spec must define two distinct implementation architectures to evaluate during the Phase 1 spike:
  - **Option A (Daemon-backed)**: `claude "<task_instructions>" --bg --session-id <uuid> [-w <name>] ...` (tracked via `claude agents --json` and transcript files).
  - **Option B (kilo-mcp style Detached Subprocess)**: Spawn `claude -p "<task_instructions>" --output-format json --session-id <uuid> ...` as a detached OS subprocess (`subprocess.Popen(..., start_new_session=True, stdout=log_file)`). Option B gives `claude-mcp` exact PID control, predictable log capture, and allows `--max-budget-usd`, `--fallback-model`, and `--output-format json` to work natively.

### B3. `claude agents --json` Lacks PIDs and Result Output for Background Agents
- **Location**: SPEC.md §1 & §3 (`claude_task_progress`, `claude_task_result`, `claude_task_cancel`).
- **Issue**: SPEC assumes `claude agents --json` is a complete replacement for kilo-mcp's task-record file. Real execution of `claude agents --json --all` reveals that background agents produce only:
  ```json
  {
    "id": "c539535e",
    "cwd": "/Users/Alfredo/works/dave_agent",
    "kind": "background",
    "startedAt": 1785805918089,
    "sessionId": "c539535e-eb6b-4821-941a-f0bb0e8f4713",
    "name": "install-reload-plugins",
    "state": "done"
  }
  ```
  Notice:
  1. `pid` is **omitted** for `kind: "background"` (it is only present for `kind: "interactive"`).
  2. No exit code, error message, or output text is returned.
  3. `claude agents` has no `stop`, `kill`, or `cancel` subcommand in `claude agents --help`.
- **Impact**: `claude_task_cancel` cannot resolve the OS PID from `claude agents --json`, and `claude_task_result` cannot get output from it. `claude-mcp` **must** maintain its own task-record files or inspect `~/.claude/sessions/` / `~/.claude/daemon/roster.json` / transcripts directly.
- **Remediation**: Correct §1 and §3 to state that `claude-mcp` still requires an internal task registry for PID tracking, cancellation, and result capture.

### B4. Conflation of Progress Polling with Session Resumption / Steering
- **Location**: SPEC.md §1 & §3 (`claude_task_progress`).
- **Issue**: §1 states that `-r`/`--resume <session-id>` is "the natural primitive for `claude_task_progress`/steering a running task". In §3, it mentions reading results via `claude --resume <session-id> --print --output-format json`.
- **Conflict**:
  1. Attempting to `--resume` a session that is actively running in the background will fail or create lock conflicts with the running worker.
  2. In `kilo-mcp`, `kilo_task_progress` inspects the SQLite database / transcript in read-only mode while the task runs; it never resumes the session. Session resumption is only used for follow-up steering *after* completion or cancellation (`continue_session_id`).
- **Remediation**: Clarify that `claude_task_progress` reads transcript files (`~/.claude/projects/.../<session-id>.jsonl`) read-only, while `--resume` / `continue_session_id` is strictly an execution-steering primitive for subsequent `claude_implement` invocations.

---

## 4. Important Non-Blocking Findings

### I1. Missing First-Class CLI Primitives in `claude_implement` Tool Surface
- **Observation**: `claude --help` and `claude agents --help` support several valuable flags that are missing from §3's proposed `claude_implement` signature:
  - `--agent <agent>`: Selects a custom or built-in subagent (e.g. reviewer, code-generator).
  - `--allowed-tools <tools...>` / `--disallowed-tools <tools...>`: Restricts tool execution (e.g. `Bash(git *) Edit`).
  - `--mcp-config <configs...>`: Injects custom MCP servers into the dispatched session.
  - `--settings <file-or-json>`: Custom configuration overrides.
- **Recommendation**: Add optional `agent`, `allowed_tools`, and `mcp_config` parameters to `claude_implement`.

### I2. Deterministic Session ID Pre-Allocation (`--session-id <uuid>`)
- **Observation**: `claude --help` includes `--session-id <uuid>` ("Use a specific session ID for the conversation (must be a valid UUID)").
- **Value**: Instead of waiting for Claude CLI to output or register a session ID, `claude-mcp` can generate `task_id = str(uuid.uuid4())` upfront, pass `--session-id {task_id}`, and immediately know the exact transcript path (`~/.claude/projects/<encoded-cwd>/{task_id}.jsonl`) at launch time.
- **Recommendation**: Document `--session-id` as the primary binding between `task_id` and the CLI session.

### I3. Transcript File Size and Streaming Parsing Strategy
- **Observation**: Transcripts in `~/.claude/projects/` are JSONL streams that frequently exceed 5–10MB for non-trivial sessions.
- **Risk**: Repeatedly loading and parsing the entire JSONL file on every `claude_task_progress` polling cycle will create high memory and CPU overhead.
- **Recommendation**: The spec should recommend reading the tail of the JSONL file (e.g. seek from end or reverse line streaming) for progress polling and Final Report extraction.

### I4. Worktree Lifecycle & Cleanup
- **Observation**: While `-w` / `--worktree [name]` creates worktrees natively, the CLI provides no built-in worktree deletion/cleanup command.
- **Recommendation**: Note in §1 and §3 that worktree merging, inspection, and removal (`git worktree remove`) remain standard git operations or separate tool responsibilities, exactly like in `kilo-mcp`.

---

## 5. Final Verdict

**Verdict**: `proceed with changes`

The architectural intent of `claude-mcp` is excellent and feasible. However, SPEC.md must be updated to address findings B1–B4 prior to full server implementation:
1. Revise the proposed dispatch architecture to distinguish between CLI native background (`--bg`) and detached subprocess (`-p` under `setsid`).
2. Acknowledge that `claude agents --json` does not provide PIDs or output results, preserving `kilo-mcp`'s on-disk task-tracking and reconciliation model.
3. Document the `--bare` authentication restriction (requires `ANTHROPIC_API_KEY`).
4. Decouple progress polling (transcript inspection) from session resumption (`--resume`).
