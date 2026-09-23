---
type: flow
description: Runs optional browser validation with explicit read-only evidence and degradation.
---

# Browser validation flow

`varde-browser` is an optional skill. It validates a local or deployed web
experience without changing external state.

## Install

Install the pack explicitly from `skills/`:

```sh
./install.sh --pack browser
```

The pack is independent from the seven-skill core and release capability.

## Run

1. Record the target URL, route, viewport, and requested checks.
2. Run `scripts/detect-browser.sh` from the installed skill directory.
3. If tooling is available, collect read-only visual, console, network, or
   accessibility evidence.
4. If tooling is missing, report the degraded capability and skipped checks.
5. Summarize passed, failed, and degraded checks with artifact paths.

Do not submit forms, mutate account data, publish content, deploy code, or
delete state during browser validation.

## Evidence

Every report names the target, viewport, detected tool, checks, limitations,
and artifacts. A missing browser is a bounded degraded result, never a passing
browser check.
