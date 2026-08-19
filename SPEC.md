# Spec — claude-mcp

## 0. Problem and motivation

`kilo-mcp` (sibling project, `../kilo-mcp`) lets any MCP client — Claude
Code, Claude Desktop, or another agent entirely — delegate implementation
work to a headless Kilo CLI run: fire-and-forget dispatch, live progress
polling, a final result, cancellation, and crash-proof recovery via
on-disk task records and log files, all as first-class MCP tools
(`kilo_implement`, `kilo_task_progress`, `kilo_task_result`,
`kilo_task_cancel`, plus discovery tools like `kilo_list_models`).

There is no equivalent for delegating to a headless **Claude Code** CLI
session. Today, delegating "run this task with Claude Code, not Kilo" only
works from *inside* a Claude Code session, via that harness's own
Agent/Task tool — which is not portable: a non-Claude orchestrator (Kilo
itself, a different agent framework, a CI script speaking MCP) cannot
reach it, and it isn't a standalone process you can poll/cancel/resume
independently of the parent conversation.

`claude-mcp` closes that gap: an MCP server that wraps the `claude` CLI's
own headless/background capabilities so *any* MCP client can dispatch a
Claude Code run the same way `kilo-mcp` dispatches a Kilo run — including
from a Kilo session itself, letting an architect/orchestrator pick the
right executor per task rather than being locked into one.

This is not a race against kilo-mcp — the two executors have different
strengths (cost/speed tiers, tool access, model choice) and a real
orchestrator wants to choose per task, the same way this project's own
sessions already alternate between Kilo and Codex for review work.

## 1. Key architectural finding: Claude Code already does most of the hard part natively

`kilo-mcp` had to build several things itself because Kilo's CLI doesn't
provide them: detached background process management with PID-liveness
reconciliation, git worktree creation, and a task-record file for crash
recovery (see `../kilo-mcp/server.py`'s `_spawn_kilo_background`,
`_is_pid_alive`, `_reconcile_task_if_orphaned`, `_create_worktree`).

The `claude` CLI (confirmed via `claude --help` / `claude agents --help`
on this machine, this environment's own version) already has native
equivalents for all three:

- **`--bg` / `--background`**: "Start the session as a background agent
  and return immediately (manage with `claude agents`)". This is a
  first-class background-dispatch primitive, not something to reimplement
  with `setsid`/detached subprocesses the way kilo-mcp had to.
- **`-w` / `--worktree [name]`**: "Create a new git worktree for this
  session" — worktree isolation is a session flag, not a separate
  git-plumbing helper `claude-mcp` needs to own.
- **`claude agents --json [--all] [--cwd <path>]`**: lists active (and,
  with `--all`, completed) background/interactive sessions as structured
  JSON, filterable by working directory — this is the CLI's own
  equivalent of kilo-mcp's task-record file, likely making a large part of
  kilo-mcp's manual bookkeeping unnecessary here.
- **`-r`/`--resume <session-id>`** and **`--session-id <uuid>`**: resuming
  or pinning a session id, the natural primitive for
  `claude_task_progress`/steering a running task the way kilo-mcp's
  `continue_session_id` does.
- **`--output-format json`** (with `-p`/`--print`): structured single-shot
  result capture, the likely basis for `claude_task_result`.
- **Session transcripts on disk**: this very session's own transcript is
  readable at a deterministic path under `~/.claude/projects/<encoded-cwd>/
  <session-id>.jsonl` — the natural recovery source if the MCP server
  process restarts mid-task, parallel to kilo-mcp's log-file recovery.
- **`--permission-mode <acceptEdits|auto|bypassPermissions|manual|
  dontAsk|plan>`** and **`--dangerously-skip-permissions`** /
  **`--allow-dangerously-skip-permissions`**: the non-interactive
  auto-approval knobs, parallel to Kilo's own non-interactive default.
- **`--max-budget-usd`**, **`--fallback-model`**, **`--effort`**,
  **`--model`**: per-dispatch cost/quality controls with no kilo-mcp
  equivalent to port — these are opportunities to expose *more* control
  than kilo-mcp currently offers, not just parity.

**Consequence for scope**: `claude-mcp` is likely a considerably thinner
server than `kilo-mcp` — a faithful MCP *front end* over CLI primitives
that already do the state-tracking, rather than a from-scratch task
runner. The main engineering work is: correct flag composition, JSON
result/progress parsing, mapping `claude agents --json` rows to a stable
MCP task-id space, and deciding what (if anything) still needs its own
on-disk bookkeeping for crash recovery once the CLI's own session/agent
state is accounted for.

## 2. Non-goals (this spec's scope)

- Not a general-purpose MCP wrapper for arbitrary `claude` CLI features
  (e.g. `--chrome`, `--remote-control`, `/skill` invocation) — only the
  delegation/task-lifecycle surface kilo-mcp's tool set covers.
- Not a replacement for `kilo-mcp` or a judgment that one executor is
  better — this exists so an orchestrator can choose.
- Not, at this stage, a guarantee of exact 1:1 tool-name parity with
  kilo-mcp — parity is a *starting design*, not a hard requirement; where
  Claude Code's own primitives suggest a better shape (e.g. because
  `claude agents --json` already gives structured multi-session listing),
  the tool surface should follow what the CLI actually provides.

## 3. Proposed tool surface (draft — validate against real CLI behavior before locking)

Modeled on `kilo-mcp`'s proven tool names/shapes (see
`../kilo-mcp/README.md` "Features" and `server.py`'s `@mcp.tool()`
definitions), adapted to Claude Code's native primitives from §1:

- `claude_implement(task_instructions, model?, effort?, permission_mode?,
  isolation?, working_directory?, max_budget_usd?, background=true)` →
  dispatches via `claude -p "<task_instructions>" --bg --output-format
  json [-w <name>] [--model ...] [--effort ...] [--permission-mode ...]`,
  returns a `task_id` immediately. Exact interplay between `-p` and `--bg`
  (does `--bg` alone already imply non-interactive/no-TTY behavior, or
  must both be passed together?) is unverified — first implementation task
  must confirm this experimentally before locking the dispatch command.
- `claude_task_progress(task_id)` → backed by `claude agents --json
  --cwd DIR` filtered/matched to this task's session id, surfacing whatever
  live state the CLI reports (kilo-mcp additionally reads Kilo's own
  session DB for a plan/todo list and commentary tail — check whether
  Claude Code's own transcript JSONL offers an equivalent lightweight
  "live progress" read without pulling the entire transcript into the MCP
  server's own memory).
- `claude_task_result(task_id)` → final structured result, likely via
  `claude --resume <session-id> --print --output-format json` or by
  reading the session transcript's final assistant message directly, plus
  exit code / completion status from `claude agents --json --all`.
- `claude_task_cancel(task_id)` → needs investigation: `claude agents
  --help` shows no obvious stop/kill subcommand in this version, so this
  may require resolving the session's OS PID and sending a signal, the
  same way kilo-mcp does today, rather than a clean CLI-native cancel.
- `claude_list_models` / `claude_auth_status` — thin wrappers if the CLI
  exposes equivalents (`claude --model` accepts aliases like `sonnet`/
  `opus`/`fable`; `claude auth` is a real subcommand per `claude --help`'s
  Commands list).
- Deliberately **not** porting kilo-mcp's `kilo_rag_search` (Claude Code
  has no built-in codebase RAG index to wrap) or `kilo_log_issue`/
  `kilo_metrics` in a first version — revisit once the core lifecycle
  tools are proven.

## 4. Known gotchas to design around (from initial research + real `--help` output)

- `-p`/`--print` explicitly skips the workspace-trust dialog and silently
  ignores invalid settings files in non-interactive mode — good for
  unattended dispatch, but means a malformed project config fails silently
  rather than loudly; `claude_implement` should surface this risk in its
  tool description.
- `--bare` skips hooks/LSP/plugin sync/CLAUDE.md auto-discovery entirely —
  worth exposing as an opt-in flag for fully deterministic, no-surprises
  dispatch, parallel to how kilo-mcp's non-interactive mode avoids
  picking up ambient state unexpectedly.
- No first-party MCP server (Anthropic or community) currently implements
  this task-runner shape — community wrappers
  (`KunihiroS/claude-code-mcp`, `steipete/claude-code-mcp`,
  `nayagamez/claude-cli-mcp`) are one-shot tool wrappers (review/fix/
  explain), not background dispatch + progress + result + cancel. Worth a
  final check of each before writing code, in case one has grown this
  shape since first surveyed (2026-08-19).
- `--allow-dangerously-skip-permissions` vs `--dangerously-skip-
  permissions`: the former just *makes bypass mode available* to
  dispatched sessions without defaulting to it (relevant for `claude
  agents`' own default-session options), the latter *is* the bypass flag.
  Easy to conflate; the tool description must be explicit about which one
  `claude_implement` actually passes and why.

## 5. Phased roadmap

1. **Spike (no MCP server yet)**: by hand, run a real `claude -p "<trivial
   task>" --bg --output-format json` dispatch in a scratch repo, then
   `claude agents --json --cwd <dir>`, then attempt a result read via
   `--resume`. Record actual JSON shapes observed — this spec's §3/§4 are
   working hypotheses from `--help` text and a research pass, not
   confirmed behavior.
2. **Minimal server**: `claude_implement` + `claude_task_result` only,
   foreground-blocking (`background=false` equivalent) to validate the
   dispatch/result round trip before adding the async task-tracking layer.
3. **Background + progress + cancel**: add real `task_id` tracking,
   `claude_task_progress`, and solve cancellation (§3).
4. **Isolation + discovery**: `-w` worktree passthrough, `claude_list_
   models`/`claude_auth_status`.
5. **Parity review**: compare against `kilo-mcp`'s feature list once the
   core loop is solid; decide per-feature whether porting it (metrics,
   RAG-equivalent, Agent Manager integration) is worth it here, rather
   than porting everything by default.

## 6. Grounding sources

- `../kilo-mcp/README.md`, `../kilo-mcp/server.py`, `../kilo-mcp/
  ARCHITECTURE.md`, `../kilo-mcp/SPEC_MCP_ORCHESTRATION.md` — proven
  design to adapt, not copy blindly (Kilo's CLI and Claude Code's CLI
  differ in what they provide natively — see §1).
- `../ai-architect-executor` — the protocol-agnostic architect/executor
  pattern (discovery, isolation, delegation, monitoring, verification,
  closure) `kilo-mcp` is a binding of; `claude-mcp` should be read as a
  second binding of the same pattern, not a new pattern.
- `claude --help` / `claude agents --help` output captured on this
  machine, 2026-08-19 — re-run before implementation starts; CLI flags
  drift between versions and this spec's §1/§3 cite this one snapshot.
