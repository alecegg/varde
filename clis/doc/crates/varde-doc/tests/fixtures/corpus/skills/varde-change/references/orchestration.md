# Orchestration

The main agent orchestrates and stays available to the user. Delegate bounded
work to background `varde-*` agents.

## Cap

- At most `[orchestration] max_agents` subagents in flight (the installed
  instruction block shows the active value). `varde-explorer` runs do not count.
- `varde-explorer` never spawns.

## Pre-explore

Only OpenCode and Pi (which needs pi-subagents) let planners, builders, and
reviewers spawn `varde-explorer` and nothing else; on other harnesses they
spawn nothing.

On other harnesses, before dispatching a planner, builder, or reviewer:

1. Run up to 2 `varde-explorer` over the task's owned and affected areas.
2. Put their notes in the brief.

The subagent uses the `varde-explore` skill only for gaps.

## Brief

When `varde` is installed, run `varde setup watch --ensure --repo
<repo-root>` before the first dispatch, retrying once with escalated access;
sandboxed subagents cannot start it.

### Writer launch

Before dispatching a writer, resolve the permission manifest and launch
contract in `references/build-worktree.md`. Supply its exact cwd and session
permissions through a supported launcher; if unavailable, report the limit
before launch. Require the worker's actual-sandbox preflight before edits.
A parent-side probe cannot establish the worker's permissions.

### Brief contents

Each brief gives one bounded task and:

- file ownership;
- orientation: files and line ranges you read, key symbols, decisions made,
  and exact check commands, seeded from `varde map context_pack` minus
  unrelated hits;
- resolved `<working>` and `<knowledge>` paths;
- the spawn rule: explorers only, up to 2, or none;
- "Do the work yourself; do not launch other subagents."

## Results

- Review each result before integrating it.
- Builders run lint and their task checks. The orchestrator runs reviews and
  full suites.
