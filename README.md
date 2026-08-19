# claude-mcp

An MCP server that lets any MCP client delegate work to a headless
**Claude Code** CLI session — the `kilo-mcp` pattern
(`kilo_implement`/`kilo_task_progress`/`kilo_task_result`/
`kilo_task_cancel`), applied to `claude` instead of `kilo`.

Status: **spec only, no code yet.** See [`SPEC.md`](SPEC.md) for the
problem statement, the real `claude` CLI primitives this will be built on
(`--bg`, `-w`/`--worktree`, `claude agents --json`, `--resume`), and the
phased plan starting with a manual CLI spike to confirm the exact dispatch/
result round trip before any server code is written.

Sibling project `../kilo-mcp` is the proven reference implementation of
the same pattern for Kilo Code — read its `README.md`/`server.py` before
starting implementation here.
