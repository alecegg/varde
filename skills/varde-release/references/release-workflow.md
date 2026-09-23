# Release workflow evidence

Use this reference after defining the release target and requested action.

## Phases

### Preparation

Record the version, source revision, target environment, provider, change
window, operator, and requested action. Write a dry-run checklist before
changing external state.

### Publication and deployment

Publication and deployment change external provider state. Get explicit
authorization for that action immediately before running its provider command.
Do not treat preparation or verification evidence as authorization.

Run `scripts/authorize-release-action.sh publish` or `deploy` immediately
before the matching provider command. A non-zero result stops the action; do
not run the provider command. Set authorization only for that invocation.

### Monitoring

Record the observation window, health signals, logs, alerts, and stop criteria.
Monitoring reads state only unless a separately authorized action is requested.

### Verification

Check the deployed version, health endpoints, critical user paths, and expected
artifacts. Separate passed, failed, and unavailable checks.

### Rollback

Record the rollback target, trigger, owner, validation checks, and observation
window. Rollback changes state and requires its own explicit authorization,
even when publication or deployment was authorized earlier.
Run `scripts/authorize-release-action.sh rollback` immediately before any
rollback provider command.

## Capability result

Report these fields for each release run:

```text
Capability: available | degraded
Provider tools: <detected tools or unavailable>
Target: <environment and release target>
Action: prepare | publish | deploy | monitor | verify | rollback
Authorization: not required | granted | absent | rejected
Passed: <checks with evidence>
Failed: <checks with evidence>
Degraded: <checks that could not run and why>
Artifacts: <checklists, logs, or none>
```

When tooling is unavailable, copy the probe's `capability`, `reason`, and
`guidance` fields into the report. Do not claim evidence from the provider.
