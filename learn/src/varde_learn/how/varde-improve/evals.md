---
topic: varde-improve/evals
version: 2
summary: Eval step 1 of 6 - cost gate, cases and assertions; then calibrate, run, compare, grade, trigger
---

# Skill evaluation and trigger query sets

An output eval checks whether a stable skill improves task results against a
no-skill baseline; a trigger eval checks whether its description triggers it.

Harness runs and judge calls can incur charges: run no evaluation session until
the user explicitly approves the run and its cost.

## Cases and assertions

Eval files edit the skill: load `varde-build`: use your skill tool, or read `../../varde-build/SKILL.md`, and route them through it.

1. Create `evals/evals.json` as `{skill_name, evals:[...]}`, each eval with:
   - `id` and a realistic `prompt`;
   - a human-readable `expected_output`;
   - judge-graded `assertions`;
   - optional deterministic `assert` fixtures;
   - optional `environment_limited: true` to exclude environment-blocked evals
     from runs and scoring;
   - optional `files`, `setup_script`, and `verification_script`.

| Assertion kind | Required keys |
|---|---|
| `file_contains` | `path`, `contains` |
| `file_absent` | `path` |
| `command_exit` | `command`, `exit_code` |
| `event_order` | `events` |
| `no_write_outside` | `allowed_paths` |
