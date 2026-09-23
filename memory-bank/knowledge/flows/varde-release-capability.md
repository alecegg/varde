---
type: flow
description: Prepares releases with explicit authorization and bounded capability evidence.
---

# Release capability flow

`varde-release` is an optional skill installed through the shipping pack:

```sh
./install.sh --pack shipping
```

Shipping is independent from the seven-skill core and browser capability.

## Prepare

1. Record the version, source revision, target environment, provider, and
   requested action.
2. Probe provider tooling with `scripts/detect-release-tools.sh`.
3. If tooling is missing, report `capability=degraded` with the probe reason
   and guidance. Do not claim provider evidence.
4. Build a dry-run checklist with artifacts, health signals, monitoring window,
   verification checks, and rollback criteria.

Preparation, monitoring, and verification planning do not mutate external
systems.

## Authorize mutations

Publication, deployment, and rollback are separate external mutations. Run
`scripts/authorize-release-action.sh` for the specific action immediately before
its provider command:

```sh
scripts/authorize-release-action.sh publish
scripts/authorize-release-action.sh deploy
scripts/authorize-release-action.sh rollback
```

A missing authorization stops the action before any provider command. Previous
authorization does not cover another mutation.

## Monitor and verify

Record the observation window, health signals, logs, alerts, stop criteria,
deployed version, health endpoints, critical user paths, and expected
artifacts. Separate passed, failed, and unavailable checks.

## Roll back

Record the rollback target, trigger, owner, validation checks, and observation
window. Request and record fresh authorization before rollback execution.
