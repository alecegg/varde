# Orchestration

The main agent orchestrates and stays available to the user. Delegate bounded
work to background `varde-*` agents.

## Cap

- At most `[orchestration] max_agents` subagents in flight (the installed
  instruction block shows the active value). `varde-explorer` runs do not count.
- `varde-explorer` never spawns.

## Pre-explore

Only OpenCode and Pi (which needs pi-subagents) let planners, executors, and
reviewers spawn `varde-explorer` and nothing else; on other harnesses they
spawn nothing.

On other harnesses, before dispatching a planner, executor, or reviewer:

1. Run up to 2 `varde-explorer` over the task's owned and affected areas.
2. Put their notes in the brief.

The subagent uses the `varde-explore` skill only for gaps.

## Brief

Each brief gives one bounded task and:

- file ownership;
- minimal context;
- resolved `<working>` and `<knowledge>` paths;
- the spawn rule: explorers only, up to 2, or none;
- "Do the work yourself; do not launch other subagents."

## Results

- Review each result before integrating it.
- Executors run lint and their task checks. The orchestrator runs reviews and
  full suites.
