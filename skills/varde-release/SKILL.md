---
name: varde-release
description: "Prepare and verify releases with explicit authorization for publication, deployment, and rollback. Report degraded capability when provider tooling is unavailable."
---

# Prepare and verify releases

Use this skill to prepare, publish, monitor, verify, or plan rollback.
Read `references/release-workflow.md` before acting.

## Workflow

1. Record the release target, version, environment, provider, and requested
   action. Do not change provider state during preparation.
2. Run `scripts/detect-release-tools.sh` from this skill's directory. Treat its
   output as the capability result.
3. Write a release checklist and record dry-run results. Include artifacts,
   health signals, monitoring windows, verification checks, and rollback
   criteria.
4. Before publication, deployment, or rollback, run the authorization guard for
   that action. Authorize each action separately.
5. Report preparation, capability, authorization, verification, monitoring, and
   degraded steps. If the action stopped, say it stopped.

## Safety boundary

You may prepare, monitor, and plan verification without authorization to change
provider state. Publication, deployment, and rollback stop before provider
commands unless the user explicitly authorizes each action.

## Available script

- `scripts/detect-release-tools.sh` reports provider tooling on `PATH`.
- `scripts/authorize-release-action.sh` checks explicit authorization for one
  release action per call.

## Gotchas

- This skill does not install release tooling.
- Missing provider tooling means capability is degraded. It does not mean the
  release passed.
- Never infer publication, deployment, or rollback from preparation evidence.
