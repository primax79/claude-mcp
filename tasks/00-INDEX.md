# Task Index — claude-mcp

Live task registry for implementing `claude-mcp`. Specification: [`../SPEC.md`](../SPEC.md).

## Initiatives

| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [Implement `claude-mcp` Server, Tests & Bound Skills](01-claude-mcp-server/plan.md) | open | - | M |

## Specs

| Spec | Drives |
| --- | --- |
| [../SPEC.md](../SPEC.md) | 01 |

## Next up

| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| 01.1 | P0 | [CLI Spike & Project Scaffold (`pyproject.toml`, config loader, transcript path encoder)](01-claude-mcp-server/plan.md) | claude | `Read SPEC.md and tasks/01-claude-mcp-server/plan.md (task 01.1), verify claude -p --output-format json --session-id behavior, scaffold pyproject.toml and core helpers with unit tests, and commit.` |
| 01.2 | P1 | [Core Process Spawner, Worktree Isolation & `claude_implement` / `claude_task_result`](01-claude-mcp-server/plan.md) | claude | `Read SPEC.md and tasks/01-claude-mcp-server/plan.md (task 01.2), implement detached subprocess spawner, worktree creation, claude_implement, and claude_task_result with pytest tests, and commit.` |
| 01.3 | P1 | [Tail Transcript Progress, `claude_task_wait`, `claude_task_cancel` & Crash Recovery](01-claude-mcp-server/plan.md) | claude | `Read SPEC.md and tasks/01-claude-mcp-server/plan.md (task 01.3), implement read-only JSONL tail progress, claude_task_wait, process-group cancel, and orphan reconciliation with pytest tests, and commit.` |
| 01.4 | P1 | [Discovery & Telemetry Tools (`claude_list_models`, `claude_auth_status`, `claude_log_issue`, `claude_log_decision`, `claude_metrics`)](01-claude-mcp-server/plan.md) | claude | `Read SPEC.md and tasks/01-claude-mcp-server/plan.md (task 01.4), implement discovery and telemetry tools with pytest tests, and commit.` |
| 01.5 | P2 | [Generate `claude-mcp-*` Bound Skills from `ai-orchestration` Templates & Marketplace Manifests](01-claude-mcp-server/plan.md) | claude | `Read SPEC.md and tasks/01-claude-mcp-server/plan.md (task 01.5), create bindings/*.json and scripts/regenerate_bound_skills.py, generate claude-mcp-* skills and indices, verify --check exits 0, and commit.` |

## Tasks by category

*(All tasks are currently structured under Initiative `01` above).*

## Decisions waiting

| Task / Initiative | Question (exact) | Decider | Blocks |
| --- | --- | --- | --- |
| - | None — Option B (detached `claude -p --output-format json --session-id <uuid>` subprocess) locked per `SPEC.md` §1.1. | - | - |

## Done

| Id | Task | Result | Closed |
| --- | --- | --- | --- |
