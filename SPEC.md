# Spec — claude-mcp

> Revised per round-001 spec review
> ([`reviews/001-spec-review-kilo-gemini-3.7-flash.md`](reviews/001-spec-review-kilo-gemini-3.7-flash.md),
> findings B1-B4) — the review ran the real CLI itself rather than trusting
> `--help` text alone, and found the first draft overclaimed how thin a
> server this could be. A second engine's review is still pending (Codex
> hit its usage limit during round 001; re-run before implementation
> starts).

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
  JSON, filterable by working directory. **Corrected by round-001 review
  (B3), verified against real output on this machine**: a `background`
  session's row is coarse — `{id, cwd, kind, startedAt, sessionId, name,
  state}` — and specifically **omits the OS PID**, exit code, error
  detail, and final output that only `kind: "interactive"` rows carry.
  This is *not* a drop-in replacement for kilo-mcp's task-record file; see
  the revised "Consequence for scope" below.
- **`--session-id <uuid>`**: lets the caller pre-allocate the session id
  *before* dispatch, rather than parsing it out of the CLI's own output —
  gives `claude-mcp` a deterministic `task_id` ↔ transcript-path mapping
  from the moment it calls `claude`, closing the "how do I even find this
  task's session id" problem the original draft left open.
- **`--output-format json`** (with `-p`/`--print`, foreground only):
  structured single-shot result capture for a synchronous dispatch.
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

**Consequence for scope — corrected after round-001 review**: the first
draft of this spec claimed `claude-mcp` would be "considerably thinner"
than `kilo-mcp` because `claude agents --json` looked like a drop-in
task-record replacement. It isn't (§1's `claude agents --json` bullet,
finding B3): no PID, no exit code, no output for background sessions.
`claude-mcp` therefore still needs a process-management and
transcript-reading layer comparable to `kilo-mcp`'s own — likely by
spawning `claude -p ... --output-format json --session-id <uuid>` as a
detached OS subprocess it tracks itself (PID, log file, on-disk task
record), the same shape kilo-mcp already uses, rather than by delegating
tracking to `claude agents`. What Claude Code's CLI still saves real work
on: worktree creation (`-w`, no git-plumbing helper needed) and a
deterministic transcript path once `--session-id` is pre-allocated (no
log-file-format reverse-engineering needed, unlike kilo's own session DB).
See §3 for the two concrete dispatch architectures (daemon-backed vs.
detached-subprocess) to evaluate in the Phase 1 spike.

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
  **round-001 review finding B2: the original draft's proposed dispatch
  command combined `-p`/`--print` (synchronous foreground) with `--bg`
  (background daemon) — these are two different, incompatible execution
  models, not two independent flags.** `--output-format`,
  `--max-budget-usd`, and `--fallback-model` also only work with
  `-p`/`--print` per `--help`. The Phase 1 spike (§5) must evaluate both
  real alternatives before either is locked in:
  - **Option A — daemon-backed**: `claude "<task_instructions>" --bg
    --session-id <uuid> [-w <name>] [--model ...] [--effort ...]
    [--permission-mode ...]`, tracked via `claude agents --json` plus
    transcript reads. Simpler dispatch command, but inherits B3's gap (no
    PID/exit-code/output from `claude agents` itself) and B1's
    (`--max-budget-usd`/`--fallback-model`/`--output-format` don't apply
    here since `-p` isn't used).
  - **Option B — detached subprocess (kilo-mcp's own shape)**: spawn
    `claude -p "<task_instructions>" --output-format json --session-id
    <uuid> [--model ...] [--effort ...] [--permission-mode ...]` as a
    detached OS process (`start_new_session=True`/`setsid`, stdout to a
    log file), the same pattern `kilo-mcp`'s `_spawn_kilo_background`
    already uses. Gives `claude-mcp` real PID control and lets every
    `-p`-only flag work, at the cost of owning the detached-process
    lifecycle itself rather than delegating it to `claude agents`.
- `claude_task_progress(task_id)` → **round-001 review finding B4**: do
  not resume the session to check progress — resuming an *actively
  running* background session risks a lock conflict with the live worker.
  Read the session transcript (`~/.claude/projects/<encoded-cwd>/
  <session-id>.jsonl`) read-only instead, the same way kilo-mcp's
  `kilo_task_progress` reads Kilo's session DB read-only while the task
  runs. Given transcripts can reach 5-10MB (round-001 review I3), read
  from the tail rather than parsing the whole file on every poll.
- `claude_task_result(task_id)` → final structured result from the
  transcript's last assistant message/turn, plus completion status. If
  Option A (daemon-backed) was chosen, cross-check `state` from `claude
  agents --json --all`; if Option B (detached subprocess), use the
  tracked process's exit code directly — do **not** rely on `--resume
  --print --output-format json` to fetch a result (that resumes/extends
  the conversation, it isn't a read-only result fetch; also confirmed
  incompatible with an in-progress background session per B4).
- `claude_task_cancel(task_id)` → **round-001 review finding B3
  confirmed**: `claude agents --help` has no stop/kill/cancel subcommand
  in this version, and `claude agents --json`'s background rows carry no
  PID to signal even if one existed. This all but forces Option B
  (detached subprocess, §above) if `claude_task_cancel` is a hard
  requirement — `claude-mcp` must own the PID to be able to cancel
  anything running as a genuine background daemon agent.
- `claude_list_models` / `claude_auth_status` — thin wrappers if the CLI
  exposes equivalents (`claude --model` accepts aliases like `sonnet`/
  `opus`/`fable`; `claude auth` is a real subcommand per `claude --help`'s
  Commands list).
- Deliberately **not** porting kilo-mcp's `kilo_rag_search` (Claude Code
  has no built-in codebase RAG index to wrap) or `kilo_log_issue`/
  `kilo_metrics` in a first version — revisit once the core lifecycle
  tools are proven.
- **Deferred from round-001 review (I1), not blocking**: `--agent`,
  `--allowed-tools`/`--disallowed-tools`, `--mcp-config`, and `--settings`
  are all real, valuable flags `claude_implement` could expose but the
  first draft omitted — worth adding once the core dispatch/tracking loop
  (above) is proven, not before.

## 4. Known gotchas to design around (from initial research + real `--help` output)

- `-p`/`--print` explicitly skips the workspace-trust dialog and silently
  ignores invalid settings files in non-interactive mode — good for
  unattended dispatch, but means a malformed project config fails silently
  rather than loudly; `claude_implement` should surface this risk in its
  tool description.
- `--bare` skips hooks/LSP/plugin sync/CLAUDE.md auto-discovery entirely
  for fully deterministic, no-surprises dispatch — **but round-001 review
  (B1) found the first draft missed a hard requirement**: `--bare` also
  disables OAuth *and* macOS Keychain credential reading entirely
  ("Anthropic auth is strictly `ANTHROPIC_API_KEY` or `apiKeyHelper` via
  `--settings`"). A user authenticated only via `claude auth login`
  (OAuth/subscription) will get an immediate auth failure under `--bare`.
  `claude_implement` must document this plainly and either require
  `ANTHROPIC_API_KEY`/`apiKeyHelper` to be set before allowing `--bare`,
  or default to *not* passing `--bare` unless the caller opts in
  explicitly knowing this trade-off.
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
- **(round-001 review I2)** `--session-id <uuid>` lets `claude-mcp`
  generate `task_id = uuid4()` *before* dispatch and pass it straight
  through, rather than parsing a session id out of CLI output after the
  fact — use this as the primary `task_id` ↔ transcript-path binding from
  the start, not an afterthought.
- **(round-001 review I3)** transcript JSONL files can reach 5-10MB for a
  non-trivial session; `claude_task_progress` must read from the tail
  (seek-from-end or reverse line streaming), not reparse the whole file
  on every poll.
- **(round-001 review I4)** `-w`/`--worktree` creates a worktree natively,
  but the CLI has no built-in worktree removal — cleanup after a task
  completes is a separate, ordinary `git worktree remove` responsibility,
  exactly like `kilo-mcp` already handles it.

## 5. Phased roadmap

1. **Spike (no MCP server yet)**: by hand, in a scratch repo, run **both**
   Option A (`claude "<task>" --bg --session-id <uuid>`, then poll
   `claude agents --json --cwd <dir>` and read the transcript) and Option
   B (`claude -p "<task>" --output-format json --session-id <uuid>` as a
   detached subprocess) from §3. Record: actual JSON shapes, whether
   Option A's background row ever gains a PID/result once `state` becomes
   `"done"`, transcript file shape/size for a real task, and which option
   actually delivers a working `claude_task_cancel`. Pick one architecture
   from real evidence, not from `--help` text — round-001 review already
   found the original single-command proposal doesn't work as written
   (B2).
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
