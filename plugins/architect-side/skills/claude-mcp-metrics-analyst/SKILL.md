---
name: claude-mcp-metrics-analyst
description: "Evaluate claude-mcp delegation efficiency - ROI analysis via claude_metrics, decision telemetry via claude_log_decision, defect-pattern review from claude_log_issue, and feedback-loop proposals for better task specifications. Use when evaluating Claude Code delegation efficiency."
---
<!-- GENERATED FROM SKILL.template.md — DO NOT EDIT BY HAND. Run generate_binding.py to regenerate. -->

# claude-mcp-metrics-analyst

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`deep-reasoning` profile) |
| **When to Load** | Evaluating delegation efficiency, cancellation/bounce rates, and recurring defect patterns |
| **Execution Modes Supported** | **Single-Framework Native** (parallel native worktrees/subagents) and **Multi-Framework MCP / CLI** |
| **Companion Scripts** | `bin/ai-orch` |
| **Related Skills** | `orchestration-workflow`, `task-spec-authoring`, `conflict-resolver` |

This skill guides the Architect in evaluating and reporting delegation
efficiency and defect rates, using whatever telemetry the specific binding
or task history collects. Protocol-agnostic: the questions below apply
regardless of whether tasks were dispatched via Single-Framework Native
worktrees/subagents or Multi-Framework MCP connectors.

## Logic and Behavior

- **ROI Analysis:** Compare actual delegation cost against the hypothetical cost of generating the same work inline using `claude_metrics`. Detail savings and efficiency multipliers to the user.
- **Defect Tracking:** review logged defects found during verification.
  Group them by severity and category to identify patterns.
- **Cancelled/aborted runs:** a task stopped mid-flight before completion
  still consumed real resources (the Executor's subprocess ran before
  being killed) and typically has no usable outcome record since no Final
  Report was produced. A high rate of cancellations for a given kind of
  task is itself a signal worth surfacing - it usually means the spec
  needs tighter constraints or the task is a poor fit for delegation.
- **Feedback Loop:** if recurring patterns are found (e.g. missed edge
  cases, styling mismatches, frequent cancellations), propose adding
  specific guardrails to future task specifications, or creating targeted
  Executor-side skills to close the gap - see `task-spec-authoring` for how
  task-spec quality itself is the main lever on defect rate.
