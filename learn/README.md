# Daily learn review

Run `varde learn run` to review local sessions.

## Options

- `--window`: yesterday in UTC by default; also accepts `since-last` (from the
  last complete review, capped to seven days) or a `YYYY-MM-DD` UTC date.
- `--budget-tokens N`: limits model tokens across extraction and synthesis.
- `--no-model`: reports deterministic session metrics without model calls.
- `--dry-run`: lists discovery and review statuses without model calls or
  review-store writes.
- `--json`: emits machine-readable output.

## Session sources

Configure session locations in `~/.config/varde/learn/sources.toml`. Harness
tables:

- `[codex]` accepts `roots = ["path"]` and `defaults = false`.
- `[claude]` accepts `roots = ["path"]` and `defaults = false`.
- `[opencode]` accepts `roots = ["path"]` and `defaults = false`.
- `[pi]` accepts `roots = ["path"]` and `defaults = false`.
- `[ignore]` accepts `paths = ["path"]` to exclude a path and descendants.
- Paths expand `~` and environment variables.

Default roots:

- Codex: `$CODEX_HOME` or `~/.codex`.
- Claude Code: `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`.
- OpenCode: its data root.
- Pi: `$PI_CODING_AGENT_SESSION_DIR` or `~/.pi/agent/sessions`.

## Store and reports

- Model review state is appended to `reviewed.jsonl`.
- Non-dry runs take a store lock; concurrent runs fail with an already-running
  error.
- Redacted reports are written to `reviews/<date>.md`.
- A session may be `pending` when a token budget or rate limit stops review.

## Scheduled review

The runner's Daily learn review job is opt-in and disabled by default.
Configuration:

- It runs at 04:00 UTC with a 100,000-token default budget.
- Set the budget through `PUT /api/jobs/review/budget` with
  `{"run_budget_tokens": N}`; accepted values are positive integers up to
  10,000,000.
- The dashboard reports job status.
- The dashboard reports coverage.
- The dashboard reports token use.
- The dashboard reports the report path.
