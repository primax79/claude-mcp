---
name: claude-mcp-orchestrator
description: "Orchestrate Claude Code CLI (the Executor) through the claude-mcp server - worktree isolation (claude_implement's own isolation='worktree'), non-blocking parallel delegation via claude_implement, deterministic completion wait (claude_task_wait) and tail-transcript progress monitoring (claude_task_progress/claude_task_cancel/continue_session_id), verification of Final Reports, defect and decision telemetry (claude_log_issue/claude_log_decision), and capture of work that emerges mid-session as task files in the repository. Use when coordinating development work through the claude-mcp tools."
---
<!-- GENERATED FROM SKILL.template.md — DO NOT EDIT BY HAND. Run generate_binding.py to regenerate. -->

# claude-mcp-orchestrator

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`orchestration` profile) |
| **When to Load** | Coordinating multi-step or parallel development, discovery, worktree isolation, monitoring, and verification |
| **Execution Modes Supported** | **Single-Framework Native** (in-framework parallel worktrees & subagents, zero MCP required) and **Multi-Framework MCP / CLI** (cross-framework delegation) |
| **Companion Scripts** | `bin/ai-orch`, `scripts/tasks_engine.py`, `scripts/orchestration_config.py` |
| **Related Skills** | `task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `conflict-resolver`, `orchestration-metrics` |

This skill is designed for an Orchestrating AI (e.g. Kilo, Claude, Codex) to coordinate headless Claude Code CLI sessions (the Executor) using Worktrees, non-blocking Parallel Execution, Tail Monitoring, and Issues Tracking.

## Role discipline: delegate, don't implement

You are the architect/orchestrator, not the implementer. When a task is
scoped for delegation (a plan/macroplan task, or any request to "implement
X" that this skill's description matches), implementation work goes
through `claude_implement` - not your own `Edit`/`Write` tools. This holds
even when a task looks small or fast to do yourself; "it's simple, I'll
just do it" is exactly how delegation gets silently skipped. If `claude_implement`
is unavailable or fails, stop and say so instead of implementing in its
place - don't silently fall back to doing the work yourself.

The one exception is **verification-phase minor fixes**: while reviewing a
Final Report (Phase 5 below), you may correct a small, obvious issue
yourself directly in Claude's worktree - a typo, a wrong import, a
misnamed variable - without a full round-trip. Anything bigger than a
handful of lines, or that touches actual logic, goes back to Claude via
`claude_implement(continue_session_id=..., task_instructions="<corrective instructions>")`, not a direct edit. When
in doubt, delegate rather than fix it yourself.

## Logic and Behavior

- **Phase 1 - Discovery:** Explore the repository before designing solutions. Confirm Claude's CLI readiness, model lineup, and credentials with `claude_list_models` and `claude_auth_status` once per session or after a dispatch failure.
- **Phase 2 - Isolation:** When delegating non-trivial changes, pass `isolation='worktree'` directly on the `claude_implement` call (auto-creates `.claude/worktrees/<branch>` and executes there). Git worktrees isolate filesystem writes, but do NOT isolate network ports or shared databases. Explicitly assign each parallel worker a distinct port from `worker_port_range` in the task specification.
  - **Worktree isolation does NOT isolate the repository's own configuration.**
    `.git/config` is shared by every worktree of a repo, so a delegated task that
    runs `git config` - or any tool that runs it on your behalf, e.g. `husky
    init` setting `core.hooksPath` - writes into the configuration the user's
    *own* checkout reads (see `references/incidents.md` #3). Any task that would touch
    repo-level configuration must be instructed to create the files and **document
    the activation command instead of running it**, and to prove it didn't by
    showing `git config --get <key>` returning empty. Activation is the user's
    call, not the task's.
- **Phase 3 - Delegation:** Use `claude_implement` to delegate implementation work. It runs in the **background by default** and returns a `task_id` immediately — never block the conversation waiting on it. Pass `focus_files` found during search, configure any `skills_to_load`, and dispatch tasks in parallel across worktrees. For work that spans multiple dependent steps or sessions, write it up first as a `tasks/` pipeline (see the `task-pipeline` skill) and delegate one task file at a time.
- **Phase 4 - Monitoring & Intervention:** Scale how closely you watch a task to its complexity/risk:
  - **Small, well-scoped tasks:** await completion deterministically with `claude_task_wait(task_id=..., timeout_seconds=...)` instead of polling timer loops.
  - **Large, multi-file, or high-risk tasks:** inspect live progress periodically with `claude_task_progress(task_id)` which reads the tail of Claude's internal project transcript without locking the session.
  - **If a task drifts off-spec or stalls:** cancel it cleanly with `claude_task_cancel(task_id)` (sends SIGTERM/SIGKILL to the detached process group). You can then steer the same session with corrective instructions using `claude_implement(continue_session_id=..., task_instructions=...)`.
- **Phase 5 - Verification & Review: NEVER trust the Final Report alone.**
  Inspect results with `claude_workspace_status`, then actually **execute** what was built — reading the Final Report or the diff is not verification, it's a summary.
- **Phase 5b - Verify the integration, not only the tasks.** Every task in a
  batch can be green in its own worktree and the merged result still be broken:
  tasks branched from the same commit cannot see each other (see `references/incidents.md` #6
  for the duplicate symbol collision incident). The integration gate is therefore
  not the union of the tasks' own criteria: after every merge run lint, tests,
  **and a full build of a consuming application**, and treat that as the batch's real acceptance.
- **Phase 6 - Closure & Telemetry:** Record the orchestration branch taken with `claude_log_decision` (`delegate`, `inline`, `escalate`, or `discarded`), and if defects are found during review, log them with `claude_log_issue` (vital for continuous prompt/specification tuning — see `claude-mcp-metrics-analyst`) and request Claude to fix them.
  - **Merging: always checkout the target branch explicitly first.**
    Running `git merge --no-ff <feature-branch> -m "..." <target>` without
    checking out `<target>` first is a real, observed mistake (see `references/incidents.md` #7).
    Correct sequence, every time:
    `git status --short` (clean) → `git checkout <target>` (explicit,
    never implicit) → `git merge --no-ff <feature-branch> -m "..."` →
    `git log --oneline --graph -6` (confirm the merge landed where
    intended).
  - **Worktree & Branch Lifecycle Cleanup (Every Terminal Path):** Remove
    the isolated worktree (`git worktree remove <path>`) not only after a
    successful merge, but also whenever a run is **cancelled** or
    **discarded** (`dropped`), so stale worktrees never linger on disk.

## Economic Rules and Cost Control in Orchestration

Software engineering agents operate in multi-turn loops where context accumulates rapidly (30k–200k tokens per turn). Empirical production data across 573 runs ($532 total shadow spend) proves that an unconstrained agent can burn $200+/day on routine tasks. Always enforce these **7 binding economic rules**:

1. **Incremental Dispatch, Not Scheduled Full Passes:**
   Only dispatch an agent task on a component or repository when its pinned Git commit hash has changed. Never re-scan or re-delegate across a repository corpus on a timer (a full pass on 640 repos costs ~$1,440–$2,470; commit-triggered runs reduce annual spend by 98%).
2. **Flash / Bulk Model by Default, Frontier on Demand:**
   Use the `bulk-execution` model (e.g. `Gemini 3.8 Flash`, `Claude Sonnet`, `GPT-5-Codex-Mini`) by default for implementation and exploration (~$2.25/component). Promote to `deep-reasoning` (e.g. `Gemini 4 Argon`, `Claude Opus`) only where the stronger model materially changes the verdict: independent verification of high/critical findings, complex architectural specs, and subtle semantic conflict resolution. Empirical production data shows a real-world ~1.7× cost difference per component.
3. **Maximize Implicit Cache via Byte-Stable Prompt Prefixes:**
   In real production runs, fresh (uncached) input accounted for **47% of total model spend**, while implicit caching served 89% of read tokens at 20× less cost. Keep invariant prompt text (grounding rules, methodology, templates) strictly at the beginning of prompts, byte-identical across runs. Put variable context (file paths, diffs, task details) at the very end.
4. **Session Reuse for Review → Refutation / Fixes (`continue_session_id`):**
   When an agent reviews code and then refutes or fixes findings, reuse the same session (`continue_session_id` / `--resume`) rather than spawning a fresh sandbox. Running review and refutation in separate sandboxes re-reads the entire codebase from scratch, wasting ~$67 in duplicate uncached input per 100 components.
5. **Driver-Level Budget Guardrails:**
   Monitor cumulative session cost (`kilo.db`, `kilo_metrics`) and pause dispatch when a configured daily or per-run cost ceiling is reached. Never let an autonomous loop run unmonitored.
6. **Asynchronous Batch Path for Latency-Tolerant Bulk Scans:**
   For large-scale, non-interactive sweeps, prefer asynchronous Batch APIs (-50% cost reduction). Split "bulk background scan" (batchable, asynchronous) from "interactive developer orchestration" (synchronous).
7. **Factor in Scheduled Price Step-Ups:**
   Track model pricing deadlines (e.g. `Gemini 4 Argon` doubles on 2026-12-01 to $4 in / $20 out; `Gemini 3.8 Flash` holds its promotional $0.75 in / $3.75 out rate until 2026-12-31, providing a **5.33× price advantage** during December 2026).

### Model Pricing Reference Table (USD per 1M Tokens)

| Provider & Model | Cognitive Profile | Input (Uncached) | Output + Thinking | Context Cache Read | Notes & Promo Deadlines |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Google Gemini 4 Argon** | `deep-reasoning` / `orchestration` | **$2.00** *(thru Nov 30)* → **$4.00** *(Dec 1)* | **$10.00** *(thru Nov 30)* → **$20.00** *(Dec 1)* | **$0.10** → **$0.20** | Flagship reasoning; NOT on Free Tier; doubles 2026-12-01 |
| **Google Gemini 3.8 Flash** | `bulk-execution` / `exploration` | **$0.75** *(thru Dec 31)* → **$1.50** *(Jan 1)* | **$3.75** *(thru Dec 31)* → **$7.50** *(Jan 1)* | **$0.075** → **$0.15** | Agent workhorse; 2.67× cheaper than Argon (5.33× in Dec 2026) |
| **Anthropic Claude 3.5 Opus** | `deep-reasoning` | **$15.00** | **$75.00** | **$1.50** | 3.75×-7.5× more expensive than Argon; cache write: $18.75 |
| **Anthropic Claude 3.5 Sonnet** | `bulk-execution` / `orchestration` | **$3.00** | **$15.00** | **$0.30** | Standard workhorse; 2×-4× more expensive than Flash; cache write: $3.75 |
| **Anthropic Claude 3.5 Haiku** | `exploration` | **$0.80** *(≤128k)* | **$4.00** *(≤128k)* | **$0.08** | Near price-parity with Flash for high-volume read-only |
| **OpenAI GPT-5-Codex** | `deep-reasoning` / `orchestration` | **$5.00**–**$10.00** *(est)* | **$20.00**–**$40.00** *(est)* | **$1.25**–**$2.50** | Flagship codex engine |
| **OpenAI GPT-5-Codex-Mini** | `bulk-execution` / `exploration` | **$1.10** | **$4.40** | **$0.55** | Fast lightweight codex engine |

### Suggested Models & Effort per Activity / Mode

| Activity / Mode | Cognitive Profile | Recommended Model & Effort/Variant | Rationale |
| :--- | :--- | :--- | :--- |
| **Architect / Plan / Design** | `orchestration` / `deep-reasoning` | **Gemini 4 Argon** (`medium`/`high`) or **Claude Opus** (`high`/`xhigh`) | Error is silent: flawed architecture poisons all downstream code. |
| **Independent Verification / Code Review** | `deep-reasoning` | **Gemini 4 Argon** (`high`) or **Claude Opus** (`high`) | Must catch subtle logic/security flaws without authorship bias. |
| **Root-Cause Debug / Tricky Bug** | `deep-reasoning` | **Gemini 4 Argon** (`high`) or **Claude Opus** (`xhigh`) | Ambiguous by nature; wrong hypothesis costs hours. |
| **Semantic Conflict Resolution** | `deep-reasoning` | **Gemini 4 Argon** (`high`) or **Claude Opus** (`high`) | Design decision disguised as merge; mechanical tools compile broken logic. |
| **Bulk Implementation (Worktree)** | `bulk-execution` | **Gemini 3.8 Flash** (`medium`) or **Claude Sonnet** (`high`) | Tests and linters catch noisy errors; Flash cuts token cost by 60%–80%. |
| **Mechanical Refactor / Tests / UI** | `bulk-execution` | **Gemini 3.8 Flash** (`medium`) or **Claude Sonnet** (`medium`) | High volume, spec-bounded, automated verification. |
| **Exploration / RAG / Q&A / Commit** | `exploration` | **Gemini 3.8 Flash** (`low`) or **Claude Haiku** (`low`) | Read-only, large context, fast deterministic response. |

### Logic & Commands to Recreate and Keep the Table Updated

1. **Online Pricing Sources to Check for Rate Changes:**
   - **Google Gemini API:** [`https://ai.google.dev/gemini-api/docs/pricing`](https://ai.google.dev/gemini-api/docs/pricing)
   - **Anthropic Claude API:** [`https://www.anthropic.com/pricing`](https://www.anthropic.com/pricing)
   - **OpenAI API:** [`https://openai.com/api/pricing/`](https://openai.com/api/pricing/)
   - Comprehensive comparative report: [`docs/07-gemini-pricing-and-role-cost-analysis.md`](../../../docs/07-gemini-pricing-and-role-cost-analysis.md)
2. **Commands to Update Mappings without Manual File Edits:**
   - Update global model assignments:
     `./bin/ai-orch config set-profile <tool> <profile> --model <id> [--variant <v>] [--effort <e>]`
   - Propagate updated model matrix into the project's `AGENTS.md`:
     `./bin/ai-orch render-agents-md --apply`
   - In Kilo Code, configure `~/.config/kilo/kilo.jsonc` setting `"subagent_model": "google/gemini-flash-latest"` and `"compaction": { "model": "google/gemini-flash-latest" }` to prevent the expensive default chat model from leaking into background workers.

## Analysis/exploration requests need the same specification rigor as implementation requests

"Analyze this project" is not a complete task spec - it's exactly as
underspecified as "improve the code," and an Executor handed either will
return the cheapest thing that technically satisfies it. Observed live: a
request to analyze a project came back as a few-line document restating
what the project is about and summarizing task-progress status - content
already sitting in the README and the status file, not analysis. The
Executor didn't fail the request; the request never said what analysis
meant.

Before dispatching an analysis/exploration task (report-shaped output, no
code change), state at least:

- **Scope, explicitly bounded.** Not "the project" - name the
  subsystem(s)/directories/entry points in scope, and whether the
  boundary is static (read the source) or behavioral (also run it, hit
  its endpoints, execute its tests). An unbounded scope invites a
  README-level summary because that's the only thing that fits any
  possible boundary.
- **Depth, named on a scale, not left implicit.** "Skim and summarize" and
  "trace every call site of X across the codebase" are both legitimate
  asks, but they produce completely different reports and cost - pick one
  and say so. Silence defaults to the shallow end, every time.
- **The problem categories actually wanted**, by name: correctness bugs,
  security exposure, performance/scaling limits, architectural coupling,
  test-coverage gaps, dependency/supply-chain risk, dead code, API
  inconsistency, whatever is relevant - a generic "find issues" produces a
  generic wrap-up. This is the same negative-claim/grounding discipline
  `task-spec-authoring` requires for code-changing
  tasks, applied to findings instead of diffs: every claimed problem must
  cite the real file/line/symbol it comes from, not a generality inferred
  from the README or a directory listing.
- **The deliverable's shape.** How many findings, what evidence per
  finding (citation, reproduction, severity), whether a verdict/priority
  ranking is expected, whether comparison against a baseline/spec/other
  codebase is in scope. If you want the same structure a spec/task review
  uses (executive assessment, findings by severity, per-area
  recommendations, final verdict - see
  `task-spec-authoring`'s review format), say
  that explicitly rather than assuming the Executor will reach for it on
  its own.
- **A negative instruction against restating existing docs.** Explicitly
  tell the Executor not to reproduce content already available in the
  README/status file/docs as if it were a finding - that's the specific
  failure mode observed live, and it's cheap to rule out by name.

Verification for an analysis deliverable follows the same Phase 5
discipline as code: skim-checking the report's own claims isn't
verification. Spot-check a sample of its findings against the real
file/line it cites, the same way a code diff gets actually executed
rather than just read.

## Work that emerges mid-session: capture it, whoever will do it

New work keeps appearing while you orchestrate: the user asks for something
aside from the current task, a review finds a defect out of scope, an
Executor's report raises a follow-up, a decision waits on someone, a peer
session hands something over. Work that exists only in the conversation is
lost at the end of the session or at compaction. Nobody else can pick it up,
and it occupies your context while it waits.

- **Capture first, then continue.** As soon as the work will not be finished
  and verified in the current turn, write it down as a task in the repository's
  `tasks/` tree, following the emergent-task rules of the `task-pipeline`
  convention: a task file (a folder with its context and progress once it has
  any), a unique id, a priority with a reason, and a one-line entry in the
  registry. Then go back to what you were doing.
  The reply cites the task by id and path; a "next steps" paragraph in the chat
  is not a substitute.
- **Not only for delegation.** The same capture applies to work you will do
  yourself, and to work for a person. The executor is a field of the task, not
  a reason to skip writing it. Your own tasks go through the same states and
  are not done until their Verification has been run.
- **The task is the hand-off.** When the task is later given to an Executor
  or to a fresh session, give it the task's `handoff` line and point it at the
  task's files. Do not re-explain the task from your memory: if something is
  missing, add it to the task first.
- **Verified is not yours to set on your own work, unless the user approves.**
  Someone other than the executor marks a task verified, after re-running its
  Verification; the executor may do it only once the user has explicitly
  approved the result in conversation (record when and what in the task's
  PROGRESS.md). This applies to the tasks you executed yourself too.
- **Keep your context lean.** After capturing a task, keep only its one-line
  entry in the registry. Read its files again only when you pick it up.

## Blocking questions: never decide on the owner's behalf

When an architectural, security, scope, or financial fork requires a decision,
the orchestrator must never guess or decide on the owner's behalf.

- **File questions with `ai-orch questions ask`:** Create a question file in
  `tasks/questions/Q###-<slug>.md` using `ai-orch questions ask`. Provide a
  standalone question (≤160 chars, ending with `?`), complete context,
  clear options with consequences, and link the blocked tasks (`--blocks T###`).
  The blocked tasks automatically transition to `waiting` (`decider: Q###`).
- **File questions from executors or runs:** When an Executor or headless run
  finishes and its Final Report contains a fenced ` ```ai-orch-question ` JSON
  block, the orchestrator (or the run supervisor) files it immediately via
  `ai-orch questions ask`, ensuring the question is recorded in `tasks/questions/`
  and the blocked task is marked `waiting`.
- **Batching rules:** Batch multiple questions together into one turn or review
  only when they are strictly independent. If question B depends on the answer
  to question A, ask question A first to avoid wasted effort and confusion.
