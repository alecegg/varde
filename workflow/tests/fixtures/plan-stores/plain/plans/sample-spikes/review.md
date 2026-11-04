---
type: review
verdict: approved
reviewer: varde-reviewer (session 01a138aa-9294-7021-8785-c9013a0b8f5b)
base: 8a72a99106f881c660c007960ea27ac83a9274a5
head: 510bd006ce3db55bde6ac5b3b434c011e20aeb6f
---

# Scope

Target: `py-port-spikes`, branch `task/py-port-spikes`, HEAD `73c90a4`. Reviewed `git diff 8a72a99..HEAD`, including the merge of main, against `plan.md` and all `tasks/*.md` in the active plan directory. No generated files or vendored files were excluded; all changed paths were in scope. No measured runs were performed.

## Categories

| Category | Status | Findings |
|---|---|---:|
| SPEC | complete | 2 |
| CORRECTNESS | complete | 0 |
| CODE | skipped | Spike fixtures, evidence, scripts and reports; no production-code quality issues in scope beyond the spec findings. |
| ARCHITECTURE | skipped | No production architecture change to assess in this spike-only diff. |

## [SPEC-001] Linux aarch64 packaging acceptance is not counted

**Severity:** medium
**Status:** waived
**Reason:** Linux execution testing was deferred by the user in the 2026-10-13 decision and repeated in the 2026-10-14 conditional gate decision; condition 3 is owned by sample-core.
**Location:** `spikes/packaging/results/linux-aarch64-smoke.json:3`

### Summary

The packaging task requires a Linux aarch64 install-and-run smoke test and specifies that the retained log show all 21 grammars, `varde --version`, a hook call, and enforcement of timeout, memory, and output limits. The committed smoke JSON explicitly labels the successful exploratory run `exploratory-pass-not-counted`; `packaging.md:58-60` likewise says the run is not counted as acceptance evidence. The required checks appear in that JSON, but the task's acceptance evidence is therefore marked unfulfilled while `tasks/packaging-spike.md` is done. The gate also reports the Linux aarch64 execution as a failed/pending condition, which is transparent but does not satisfy the task acceptance criterion.

### Solutions

1. Count and document the existing successful smoke as acceptance evidence, if it meets the task's required setup and provenance; otherwise perform and retain an accepted Linux aarch64 smoke run before marking the task complete.

## [SPEC-002] Toz checkpoint candidate summary omits required rows and details

**Severity:** medium
**Status:** fixed
**Location:** `spikes/toz-report.md:7`

### Summary

The `toz-checkpoint` task requires a runner candidate table with numbers and pass/fail per row. The checkpoint table summarizes six candidates, but does not include the own-binding last-resort pricing row, rejected `dukpy` and `RestrictedPython` rows, or the OS-sandbox “not tested, not a gate candidate” row required by `tasks/toz-script-runner-spike.md`. It also reduces the first two candidate controls to pass summaries instead of the required per-control values and pass/fail outcomes. The detailed `spikes/toz-scripts/results/runners.md` contains those missing rows and control evidence, so the omission is in the checkpoint report rather than the underlying spike evidence.

### Solutions

1. Bring the required candidate rows and per-control numbers/outcomes into the checkpoint table, or link a compact complete candidate table there so the checkpoint itself presents the specified evidence.

## Review evidence

- `gate/gate-report.md` contains exactly one verdict line (`verdict: conditional`); each threshold row has a numeric measured value or count and a pass/fail result. Spot checks agree with committed JSON for hook p95 and wear, behavior check totals (507/2,121 = 23.90%), index timings, and worktree/dev-loop N=5 write results.
- Hook and index measurement metadata name `ioreg IOBlockStorageDriver Bytes (Write)`, record idle measurements and state outliers retained. `scripts/with-lock.sh` acquires the shared measurement lock; measurement scripts invoke it, and hook wear checks the probe lock. The approved pre-window result paths are listed in `scripts/window-agreements.md`; `scripts/check_window.py` defines the 2026-10-19 cutoff. No measured runs were started for this review.
- `scripts/baseline-varde.txt` and current `/Users/alec/source/varde` `git status --porcelain` both contain exactly `?? fixtures/`.
- No committed virtual environments, caches, Python bytecode, or compiled package artifacts were found. The two 637,405-byte QuickJS WASM files are tracked spike/package assets.
- The report's main gate figures were consistent with their committed JSON in spot checks. The gate transparently records known scope limitations (no Linux execution counted, no previous warm-hook baseline, incomplete equal-work preview, and packaging-fixture first-index command).

## Re-check

- SPEC-002: confirmed the checkpoint report includes the own-binding pricing row, rejected dukpy and RestrictedPython rows, OS sandbox status, per-control values for candidates 1 and 2, and exactly five required level-2 headings; these details match `spikes/toz-scripts/results/runners.md`.
- SPEC-001: waiver remains legitimate; the user deferred Linux execution testing, and gate condition 3 assigns Linux checks to `sample-core` when testing is un-deferred.
- No critical or high new findings.
