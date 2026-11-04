---
status: todo
category: new-feature
title: "Anonymized sample plan"
label: "Anonymized plan title"
group: "Example"
type: plan
depends_on:
  - 2026-10-23-runner-daily-job-base
  - 2026-10-23-runner-time-helpers
shared: []
gate: []
reviewed_commit: "anonymized-sha"
reviewed_on: "2026-10-01"
custom_note: "keep: quoted value" # retained comment
assigned_to: "example-agent"
merge_approved_at: 2026-10-23T16:20:00+00:00
---

## Problem

The runner has two hard-coded daily jobs (session sweep, mail soak) with only JSON state files: no pause, no history, no dashboard view of failures.

## Solution

A built-in job registry (sweep, soak) with stored schedule, enabled flag and run history, controllable (list, pause, resume, run now) from CLI-free HTTP routes and a new `/jobs` dashboard card; one added registry row later adds an opt-in model-spending job.

## Non-goals

- User-defined commands and agent prompts (wait for native adapter cutover; queue stub then).
- The learn daily review job (plan 2026-10-23-learn-daily-review adds one registry row).
- Cron or one-off schedules; v1 keeps daily HH:MM UTC.
- Changes to Mail/queue pages or `+page.svelte` (orchestrator-3 owns them).

## Constraints

- Build on `runner/src/varde_runner/daily_job.py` and `varde_core.utc`.
- Runner store change is additive tables via `_ensure_schema`, no `user_version` bump; main backs up `runner.sqlite3` before first deploy.
- Model-spending jobs are opt-in (default disabled), flagged and showing per-run budget and cost on the card.
- UI: new route `/jobs` only; low density, action items first, no left-border accent stripes, no horizontally scrolling rows on mobile.
- Existing `/api/learn/sweep` routes and the JSON state/notification behavior stay unchanged.
- Do not touch sandbox or settings files.

## Design

### Tech choices

- Registry is plain data, not classes — a new job is one row.
- Existing `DailyJob` keeps its JSON resume/notification state; new tables hold schedule and history only — avoids migrating working state.
- Pause is checked in the scheduler loop; run-now ignores pause — an explicit user action.

### Schema / data model

- `job_schedules(job_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL, schedule_time TEXT NOT NULL, updated_at TEXT NOT NULL)`; row absent means registry defaults.
- `job_runs(id INTEGER PRIMARY KEY, job_key TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, trigger TEXT NOT NULL, outcome TEXT NOT NULL, error TEXT, model_tokens INTEGER, cost_usd REAL)`; index on `(job_key, id DESC)`; outcome in `running|succeeded|failed`; trigger in `schedule|manual`; history trimmed to the latest 200 per job.
- `JobSpec(key, title, spends_model_usage: bool, default_enabled: bool, default_time: str, run_budget_usd: float | None)`; `BUILTIN_JOBS = (sweep, soak)`; sweep and soak are `default_enabled=True`, `spends_model_usage=False` (sweep tokens are not metered yet; unchanged behavior).

### API / interface contracts

- `GET /api/jobs` → `{"jobs": [{key, title, enabled, spends_model_usage, run_budget_usd, schedule_time, next_run_at, state, last_run: {started_at, finished_at, outcome, error, model_tokens, cost_usd} | null}]}`
- `GET /api/jobs/{key}/runs?limit=20` → `{"runs": [...]}` newest first; 404 unknown key.
- `POST /api/jobs/{key}/pause`, `/resume` → the job entry; `POST /api/jobs/{key}/run` → the job entry after the run; 404 unknown key.
- Existing routes: unchanged.

## Decisions so far

- Schedule storage → additive SQLite tables, no version bump (user).
- Learn run → separate plan 2026-10-23-learn-daily-review; v1 ships sweep and soak; registry shaped for one opt-in row (user).
- v1 scope → built-in jobs only (user).

## Open Questions

n/a — no open questions

## Assumptions

- Schedule edits in v1 are pause/resume only; time editing waits — affects: design — confidence: medium
- Jobs run as one process-wide scheduler task per job, as today — affects: design — confidence: high

## Acceptance criteria

- [ ] Given a fresh store
      When the runner opens it
      Then `job_schedules` and `job_runs` exist and `PRAGMA user_version` is unchanged
      (assert: `core/scripts/test-env.sh uv run pytest runner/tests -k job_store -q` → passes)
- [ ] Given a paused job
      When its scheduled time arrives
      Then it does not run, and a manual run still records a `manual` run
      (assert: `core/scripts/test-env.sh uv run pytest runner/tests -k job_control -q` → passes)
- [ ] Given a failed run
      When `GET /api/jobs` and `/api/jobs/{key}/runs` are called
      Then the failure and error text appear
      (assert: `core/scripts/test-env.sh uv run pytest runner/tests -k jobs_api -q` → passes)
- [ ] Given the `/jobs` page on a narrow viewport
      When it renders
      Then rows wrap with no horizontal scroll and no left-border stripes
      (retrieve: `runner/ui/src/routes/jobs/`, screenshot at 390px → judged)
- [ ] Given a `JobSpec` with `spends_model_usage=True`
      When registered
      Then it defaults disabled and the card shows its budget and cost
      (assert: `core/scripts/test-env.sh uv run pytest runner/tests -k job_registry -q` → passes)
- [ ] Given the whole change
      When `just test-baseline` runs
      Then no failures
      (assert: `just test-baseline` → no failures)

## Progress

## Related

- runner/src/varde_runner/daily_job.py, sweep_job.py, soak_job.py
