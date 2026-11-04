---
status: completed
title: 'sample-spikes: measure whether a Python port of varde keeps hook latency, 21-grammar entity behavior check and packaging workable while cutting agent-worktree SSD writes, ending in a go/no-go/conditional gate report'
type: plan
depends_on: []
shared: []
reviewed_commit: 068be474362b8cdc7eb4077f309c563aac05501c
reviewed_on: 2026-10-13
---

## Problem

The main concern is SSD writes from agent worktrees. Python plain venv writes far less per fresh worktree than Go cgo, which reaches only 18 of 21 grammars; Python was never prototyped for the toz hook, toz scripts, entity behavior check, packaging or the dev loop. Measured anchors are in Design.

## Solution

Time-boxed spikes in `/Users/alec/source/varde-py` measure the Python hook, the script-runner options, extractor behavior check and index speed, ast-grep feasibility, packaging and licenses, and fresh-worktree and dev-loop writes, with a non-blocking evaluation report after the toz spikes, then a gate report states measured thresholds and a go/no-go/conditional verdict. Nothing is ported before the gate.

## Non-goals

- Any edit to `/Users/alec/source/varde` (read-only reference) or to the main branch of `/Users/alec/source/varde-py`.
- The port itself (plans `sample-core`, `python-port-modules`, `python-port-code`, and the ungated `python-port-toz`).
- Skill scripts (11 scripts, about 2,000 lines, already shell/python, no CLI duplication per inventory): they need no port.
- Index write bytes: prototypes rewrote the whole index each run, an artifact; the real `varde map build` is incremental and queries are read-only, so index writes are not a spike criterion.
- Full ast-grep matcher/rewrite/scan behavior check, and cgo-free Go.

## Constraints

- Measured tasks (any ioreg sample, venv/PyInstaller/PEX build, pytest loop) may run at any time under the shared lock `/Users/alec/source/.varde-measure.lock`, with N>=5, the idle floor, ioreg only, and no dropped outliers.
- Both locks: the idle gate must also refuse while `/Users/alec/source/agent-memory/projects/varde/working/metrics/probe/session.lock` (`device-writes-reduction` probe) exists, besides `/Users/alec/source/.varde-measure.lock`.
- Measurement is serialized by the lock; authoring is parallel. The idle gate times out after 1800 s; a timed-out sample is recorded as not-run, never retried indefinitely.
### Measurement method

- Measured tasks run only on Codex `gpt-6-luna` or Pi `deepseek/deepseek-v4-flash` (thinking high); never Claude or `sol` models.
- Wear is `ioreg` `Bytes (Write)` summed over `IOBlockStorageDriver` only, N=5, with a duration-matched idle sample; every measured command holds `/Users/alec/source/.varde-measure.lock` (mkdir lock, owner file, rmdir release) and the idle gate from `varde-py/scripts/measure-breakdown.sh`.
- Latency is wall time, p50/p95 over at least 30 runs after warmup, cold and warm separately.
- Spike code lives in `/Users/alec/source/varde-py` on task branches (never main), in `spikes/` and `gate/`; `/Users/alec/source/varde` (standard repo) and `varde-go` are read-only references. `reviewed_commit` means varde-py HEAD.
- Real behavior is the reference: `varde map build` incremental, queries read-only, linked worktrees read the main checkout's index read-only and write nothing (`varde-index-writes/docs/worktree-index-writes.md`: linked-worktree first query 0 B median).
- Versions, package names and flags are verified with the registry or `--help` and recorded; none guessed. wasmtime-py and its QuickJS-NG WASI .wasm source, Pydantic Monty, and the other runner candidates: verify existence and maturity first.
### Platforms and fixtures

- Platform coverage (testable): the matrix is `aarch64-apple-darwin` (macOS arm64), `x86_64-unknown-linux-gnu` and `aarch64-unknown-linux-gnu` (`.github/workflows/release*.yml:23-27`). macOS is measured locally. Linux x86_64 is verified by resolution (e.g. `uv pip compile --python-platform <target> --only-binary :all:`, flags verified with `--help`) or CI. Linux aarch64 must install AND run: a smoke test in a container or CI runner installs the package set, including all 21 tree-sitter grammars, and runs `varde --version`, a hook call and a script-runner call. PyInstaller does not cross-build: artifacts are sized on macOS only, Linux artifacts are documented, plus the aarch64 smoke test.
- Fixtures are copied into the spike repo; the previous index database goes under `$TMPDIR` (never `.varde/` inside `/Users/alec/source/varde`).
- Python bytecode policy is stated per measurement (e.g. `PYTHONPYCACHEPREFIX` or `sys.dont_write_bytecode`).
- Python module rules mirror `/Users/alec/source/varde/AGENTS.md`: `varde-core` depends on no `varde-*` package, `contracts package` only on core, module packages on those plus their family `-core`, only the app package on modules; no cross-family path deps.
- Task asserts use absolute paths under `/Users/alec/source/varde-py`; task `owns` are paths relative to that repo (the validator rejects absolute paths); no workspace-wide asserts.

## Design

### Tech choices

- Write anchors (ioreg, N=5; `varde-py/docs/comparison-21.md`): Python plain at 21 grammars wrote 29,470,720 B checkout, 602,112 B setup and 29,585,408 B edit rerun, about 59.7 MB per fresh worktree plus one edit (lines 25, 33); checkout is inflated by committed generated blobs (line 42). At 18 grammars Python's fresh-worktree total is 58,019,840 B and Go cgo's phase-median sum 741,388,288 B, with an edit+run loop of 123,555,840 B (lines 13, 33, 54). previous: `varde-code` fresh build 252,289,024 B (N=1), edit rebuild 188,579,840 B (line 14); workspace cold build 5.68 GB, core edit 3.87 GB (`2026-10-12-device-writes-reduction/notes/root-trace-results.md:10-11`).
- Spikes on task branches of `varde-py` with `spikes/{toz-hook,toz-scripts,code-behavior check,packaging}/`, `gate/`, `scripts/` (reuse lock and wear scripts already in `scripts/`) — keeps measuring tooling identical to prior evidence.
- Python and uv versions pinned and recorded (prior runs: Python 3.14.7, uv 0.12.19, `UV_PYTHON_PREFERENCE=only-system`) — comparability.
### Hook design

- Hook comparison target (equal work): the Python hook must, per payload, produce the same captured row count and stdout shape as previous (store write, FTS5 insert, profile/filter match, handle output); ioreg is measured over a window of K calls against a matched idle window, since one call is below resolution. Reference: previous `varde run capture --hook --harness claude-code` using payloads from `clis/benches/toz-hook.sh` (read from `/Users/alec/source/varde`).
### Toz spikes and checkpoint

- Evaluation checkpoint: the toz spikes (`toz-scripting-count`, `toz-hook-spike`, `toz-script-runner-spike`) run first. The orchestrator then writes `spikes/toz-report.md` (scripting count and classification, runner candidate table with numbers and pass/fail per row, hook latency and ioreg writes, recommendation, open risks) in task `toz-checkpoint` and reports it to the user. The checkpoint is non-blocking: the remaining spikes do not wait for approval.
- previous baseline: hook latency compares against the read-only `/Users/alec/source/varde` build, measured first in `toz-hook-spike`; it is a measurement baseline, not a port dependency.
- Maintenance risk: the quickjs-ng PyPI wrapper (and any single-maintainer wheel) gets a maintenance-risk note in the gate report.
- Toz scripting count (runs first among toz spikes; unmeasured): count existing toz scripts and profiles read-only from `/Users/alec/source/varde`, classify each as declarative (globs, regex, field select, trim, group, count) or genuinely programmatic, report the share, and conclude whether a declarative profile format (plus a narrow expression language if needed) can drop the embedded runner. The result feeds the runner decision.
### Script-runner candidates

- Script-runner candidates (no previous helper or fallback anywhere; must be Python or a Python-installable wheel enforcing timeout, memory limit and output limit identically on macOS arm64, Linux x86_64 and Linux aarch64). Ranked: (1) QuickJS-NG WASI module under wasmtime-py (wasmtime 49.0.0, 2026-09-21; wheels for macosx_11_0_arm64, manylinux1_x86_64, manylinux2014_aarch64, plus musllinux); keeps the JS scripts and API `toz.eachLine/text/exec/record/print`; spike verifies fuel/epoch timeouts, store memory limits, cold start cost, glue-code size, and vendoring or building the .wasm from upstream quickjs-ng WASI or vercel-labs/quickjs-wasi (about 620 KB); (2) pydantic-monty 1.1.0 (2026-10-05, MIT; worker process, time limits yes, memory limit not documented; Python-subset rewrite); (3) Starlark (starlark-pyo3, last seen 2023.1, maintenance unknown); (4) Lua via lupa (wheels and limits unverified); (5) quickjs-ng PyPI wrapper (genotrance/quickjs-ng: monthly auto releases, only 2 commits, open sdist build issue #11 since 2026-05-13 with no maintainer reply, so a maintenance-risk row; wheels include manylinux aarch64); PyMiniRacer is the last JS fallback; an own binding (cffi/maturin over quickjs-ng) is a documented last resort with priced LOC, CI and maintenance.
- Rejected: dukpy (ES5 Duktape, unclear releases, no limits evidence), RestrictedPython; Python in an OS sandbox is not tested and not a gate candidate.
- Each row records: wheels on all 3 platforms, enforceable timeout, memory limit and output limit (each tested with a script that exceeds it), release recency, open build issues and maintainer response.
- Gate rule: the first ranked candidate whose row passes every check wins; if none passes, the script-runner row fails and the verdict is no-go or conditional (toz scripting needs redesign before the port starts); no previous fallback.
- If `toz-scripting-count` concludes the embedded runner can be dropped, the runner row passes as "declarative format, no runner" and the user decides at the checkpoint; the candidate table is still produced.
### Behavior check design

- Entity behavior check (cause-classified): record grammar name and version per side per language (previous: `ast-grep-language 0.45.1`; varde-py: `tree-sitter-language-pack>=0.9,<1`), list both 21-language sets, and classify each diff as grammar-version difference or port bug. Also run index-speed rows (cold index, no-change refresh, 1-file edit wall time, previous vs Python, same fixtures) because incremental refresh still parses changed files in Python and the research note scored Python 2/5 on index speed.
- Entity behavior check detail: run the previous extractor and the Python extractor on the same fixtures for all 21 grammars; diff `(kind, name, line)` entities per language; list ABI mismatches and missing wheels.
### Feasibility, licenses, loop and packaging

- ast-grep feasibility: `varde-code` depends on `ast-grep-core`/`ast-grep-language` 0.45.1 (`clis/code/crates/varde-code/Cargo.toml:13,20`); verify `ast-grep-py` on PyPI (version, wheels for the three targets) and run a small sample of the repository's scan rules with previous and Python comparing match counts. Full matcher/rewrite behavior check stays out of scope; scan's fate (port or drop; previous is not kept) is a gate output.
- License gate: list each Python dependency's SPDX expression (tree-sitter-language-pack and grammars, quickjs wheels, PyInstaller bootloader, PEX, ast-grep-py) and evaluate with the same policy as the previous CI gate (commits `d509a3d7`, `a796e7c1`, `a4a9ca46`).
- Dev-loop writes: edit + scoped pytest, N=5, in the packaging workspace against the previous core-edit reference; also estimate the test-execution share of previous's full-gate writes (language-independent floor).
- "First use" is exactly: git checkout of the layout excluding committed fixture blobs + `uv sync` with a shared `UV_CACHE_DIR` + the first `varde --version` and first index command; reported by phase.
- CLI compatibility contract: argv, exit codes and the `{schema_version, ok, outcome, data, meta}` envelope stay identical; the gate reports a previous-vs-Python CLI behavior check result on the spike surface and names the full behavior check suite as a plan 2 input.
- Port size: the gate states lines per module (about 170,000 previous source lines plus about 66,000 test lines under `clis/`) and a strangler order (the previous CLI may serve as a strangler only during migration and is removed before the port ships).
- Packaging: multi-package uv workspace mirroring `clis/` crates (`varde-core`, `contracts package`, `varde-code`, `varde-toz`, ...), `uv tool install` with `--with` and extras, entry-point plugin discovery for module subcommands, `varde setup sync` and update flow, PyInstaller and PEX release artifacts: macOS only, reusing the prior sizes (PyInstaller onedir wrote about 1.07 GB to build; PEX plus shared venv about 820 MB combined; release-time cost, not per-worktree); Linux artifacts are documented, not built (SCOPE-002).

### API / interface contracts

- Spike result files: `spikes/<name>/results/*.json` with `{name, runs, wall_ms:{p50,p95}, device_bytes, idle_bytes}`.
- Checkpoint report: `spikes/toz-report.md` (non-blocking).
- Gate report: `gate/gate-report.md` with one row per threshold: measured value, threshold, pass/fail, then one verdict line `verdict: go|no-go|conditional`.
- Orchestrator copies the gate report to the set-level `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/gate-report.md`; the gate-precondition tasks read that path.

## Decisions so far

- Shape: spike-first, a non-blocking evaluation report after the toz spikes, then the gate, then port → user chose.
- Real varde-code is incremental and read-only for queries → index rewrite writes from prototypes are excluded from gating.
- Go cgo reaches 18 of 21 grammars (Dart, Haskell, Solidity declare ABI 15 while the pinned runtime supports ABI 14, a pin not a hard limit; its 512 MB build used a fresh empty cache); cgo-free Go dropped → Go is excluded from the gate (user confirmed); it is context in the report, not a candidate.
### Gate and scope decisions

- Gate thresholds accepted as drafted (Open Question 2 resolved) with two changes: behavior check rule is overall >= 99% and no language below 95%; fresh-worktree write threshold is 75 MB ioreg (PLAN-016 resolved) -> user chose.
- Accepted gate thresholds: hook p95 <= max(50 ms, 2x measured previous p95) warm and <= 3x cold; entity behavior check >= 99% of previous entities overall and no language below 95%; 21 of 21 grammars installable from wheels on macOS arm64 and Linux x86_64, and the Linux aarch64 install-and-run smoke test passes; fresh-worktree first use (defined exactly in Design) <= 75 MB ioreg against the anchor of about 59.7 MB (checkout + setup + edit rerun), excluding committed fixture blobs; script runner per the rule in Design; multi-package install works with `uv tool install` in one command. Further rows: dev-loop writes, index speed, ast-grep feasibility, license, aarch64 Linux.
- Gate verdict values: go | no-go | conditional (the port-everything-but-varde-code option was dropped by the user: previous is not kept in the port; a failed code-behavior check or index spike gives no-go or conditional for the whole port, and conditional lists each condition with an owner) (Open Question 6 resolved) -> user chose.
- Script runner (supersedes the earlier QuickJS-default rule): no previous helper or fallback; the ranked Python-or-wheel candidate list and gate rule are in Design; Python in an OS sandbox is not tested and is not a gate candidate; Seatbelt/sandbox-exec dropped (Open Question 4 closed). A toz scripting count spike precedes the runner spike and may show a declarative profile format can replace the embedded runner -> user chose.
- Scope: plans 2-4 stay gated placeholders with a gate-precondition task (SCOPE-001); packaging spike on macOS only, reusing earlier sizes, Linux artifacts documented not built, plus a Linux aarch64 install-and-run smoke test (SCOPE-002); WASM (wasmtime-py + QuickJS-NG) is spiked as runner candidate 1 and the other candidates are rated by the row checks; Linux sandboxes beyond that are documented, not tested (SCOPE-003) -> user chose.

## Open Questions

### Repository question

- 5. Target repository for the port (monorepo beside `clis/`, `varde-py`, or a new repo; affects CI, release and the read-only rule on `/Users/alec/source/varde`). Deferred by the user to re-plan after the gate; default a new repo. Status: open/deferred.

## Assumptions

- `varde-py` contains reusable extractor and index code to copy — affects: code-behavior check-spike — confidence: high
- 21 grammars cover the same language set as the previous extractor, so behavior check fixtures can be shared — affects: code-behavior check-spike — confidence: medium
- Wheels exist for Linux x86_64 and aarch64, including all 21 tree-sitter grammars; verified by the aarch64 smoke test — affects: packaging-spike, code-behavior check-spike — confidence: medium
- Index speed is gated by cold index, no-change refresh and 1-file edit rows in code-behavior check-spike rather than assumed non-binding — affects: thresholds — confidence: medium

## Acceptance criteria

### Hook and scripts

- [ ] Given the spike repo, When the hook spike ends, Then p50/p95 cold and warm latency and ioreg writes exist for previous and each Python launch style
      (assert: `python3 /Users/alec/source/varde-py/spikes/toz-hook/validate.py` → exit 0: keys previous/uv-run/entry-point, each with cold and warm entries, runs >= 30, `wall_ms.p50/p95`, `device_bytes`, `idle_bytes`, and equal row count vs previous)
- [ ] Given uv-managed Python, When FTS5 and glob behavior check are checked, Then FTS5 porter and trigram tokenizers work and every profile.rs glob test case matches
      (assert: `/Users/alec/source/varde-py/spikes/toz-hook/check.sh` → exit 0, and `check.sh --mutate` → exits 0 only when the mutated case fails)
- [ ] Given the toz scripts and profiles, When counted, Then the declarative vs programmatic share and a conclusion on dropping the embedded runner exist
      (assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/toz-scripting/results/count.json'));assert d['total']>0 and d['declarative']+d['programmatic']==d['total']" && test -s /Users/alec/source/varde-py/spikes/toz-scripting/results/conclusion.md` → exit 0)
- [ ] Given the script-runner candidates, When compared, Then a table has one row per ranked candidate with wheels on all 3 platforms, enforceable timeout, memory limit and output limit, release recency and open build issues, and the gate rule outcome (no previous fallback)
      (retrieve: `/Users/alec/source/varde-py/spikes/toz-scripts/results/runners.md` → rows wasmtime-quickjs-ng, pydantic-monty, starlark, lupa, quickjs-ng-pypi, with numbers and can/cannot-enforce columns, a maintenance-risk row for quickjs-ng-pypi, an own-binding last-resort pricing row, and rejected rows dukpy and RestrictedPython)
### Behavior check, index, packaging, writes

- [ ] Given the 21 grammars, When both extractors run on the same fixtures, Then per-language entity counts and diffs exist
      (assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/code-behavior check/results/behavior check.json'));assert len(d['languages'])==21"` → exit 0)
- [ ] Given the packaging spike, When it ends, Then a workspace builds, `uv tool install` with `--with` runs, plugin discovery lists module subcommands, and release artifacts are sized on macOS (Linux artifacts documented, not built), and Linux aarch64 installs and runs
      (retrieve: `/Users/alec/source/varde-py/spikes/packaging/results/packaging.md` → each of the five questions answered with a command and output; aarch64 smoke test log shows all 21 grammars installed, `varde --version`, a hook call, and a script-runner call with timeout, memory and output limits enforced)
- [ ] Given all spikes, When the gate runs, Then the report has a number and pass/fail per threshold and one verdict
      (assert: `grep -E "^verdict: (go|no-go|conditional)$" /Users/alec/source/varde-py/gate/gate-report.md` → one match)
- [ ] Given index and ast-grep checks, When run, Then cold index, no-change refresh and 1-file edit wall times and an ast-grep feasibility note exist
      (assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/code-behavior check/results/index-speed.json'));assert {'cold','refresh','edit1'}<=set(d)" && test -s /Users/alec/source/varde-py/spikes/ast-grep/results/feasibility.md` → exit 0)
- [ ] Given fresh-worktree and dev-loop measurements, When done, Then both result files exist with N=5
      (assert: `python3 -c "import json;[json.load(open('/Users/alec/source/varde-py/spikes/worktree-writes/results/%s.json'%n))['runs']>=5 or 1/0 for n in ('worktree','devloop')]"` → exit 0)
- [ ] Given the dependency set, When licensed, Then every dependency has an SPDX expression evaluated by the previous gate policy
      (retrieve: `/Users/alec/source/varde-py/spikes/packaging/results/licenses.md` → each dependency with SPDX and pass/fail)
- [ ] Given the three release targets, When packaging is reported, Then aarch64 macOS and aarch64 Linux are verified (installed and run); x86_64 Linux is verified or resolved-only
      (retrieve: `/Users/alec/source/varde-py/spikes/packaging/results/packaging.md` → table of aarch64-apple-darwin, x86_64/aarch64 linux)
- [ ] Given the spikes ended, When both reference repos are checked, Then nothing changed in them
      (assert: `diff <(git -C /Users/alec/source/varde status --porcelain) /Users/alec/source/varde-py/scripts/baseline-varde.txt` → exit 0; baseline recorded by repo-setup; `git -C /Users/alec/source/varde-py rev-parse main` unchanged from repo-setup)

## Progress

## Related

- Related decisions tracked: PLAN-001..020 in `notes/plan-review.md`
- Related: `2026-10-11-language-migration-spike` (separate Go/Node spike; no dependency, not superseded here).
- Reused evidence and scripts: `/Users/alec/source/varde-py/docs/{comparison.md,comparison-21.md,py-write-breakdown.md,py-levers.md}`, `/Users/alec/source/varde-go/docs/{comparison.md,worktree-writes.md}`, `/Users/alec/source/varde-index-writes/docs/worktree-index-writes.md`
- Completed prior plans: `2026-10-12-varde-go-rewrite-exploration`, `2026-10-13-varde-py-write-exploration`, `2026-10-13-py-go-21-grammar-write-compare`, `2026-10-13-varde-code-worktree-index-writes`
- Module rules: `/Users/alec/source/varde/AGENTS.md`
