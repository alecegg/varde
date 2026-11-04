---
type: task
status: done
depends_on: [repo-setup, toz-scripting-count]
owns: [spikes/toz-scripts/]
---

Scope:

- Mostly not measured (start-cost timing only, no ioreg).
- Read spikes/toz-scripting/results/conclusion.md first; it feeds this decision.
- No previous helper or fallback is acceptable.
- The runner must be Python or a Python-installable wheel with timeout, memory limit and output limit enforced identically on macOS arm64, Linux x86_64 and Linux aarch64.

Candidates:

- Candidates, ranked: (1) QuickJS-NG WASI module under wasmtime-py (wasmtime 49.0.0; verify wheels, fuel/epoch timeouts, store memory limits, cold start, glue-code size, vendoring or building the .wasm from upstream quickjs-ng WASI or vercel-labs/quickjs-wasi, about 620 KB); (2) pydantic-monty 1.1.0 (time limits yes, memory limit not documented, Python-subset rewrite); (3) Starlark (starlark-pyo3); (4) Lua via lupa; (5) quickjs-ng PyPI wrapper (genotrance/quickjs-ng; open sdist issue #11, no maintainer reply: maintenance-risk row); PyMiniRacer last JS fallback; own cffi/maturin binding over quickjs-ng as a documented last resort with priced LOC, CI and maintenance.
- Rejected without testing: dukpy, RestrictedPython.
- Do not test Python in an OS sandbox; no Seatbelt/sandbox-exec.

Rows and gate rule:

- Each row records: wheels on all 3 platforms, enforceable timeout, memory limit and output limit (each tested with a script that exceeds it), release recency, open build issues and maintainer response, start cost for tested candidates.
- Gate rule: the first ranked candidate whose row passes every check wins; if none passes, the script-runner row fails and the verdict is no-go or conditional (toz scripting needs redesign before the port starts); no previous fallback.
- If `toz-scripting-count` concludes the embedded runner can be dropped, the runner row passes as "declarative format, no runner" and the user decides at the checkpoint; still produce the candidate table.

#### Acceptance criteria

- assert: `test -s /Users/alec/source/varde-py/spikes/toz-scripts/results/runners.md` → exit 0
- retrieve: `/Users/alec/source/varde-py/spikes/toz-scripts/results/runners.md` → rows wasmtime-quickjs-ng, pydantic-monty, starlark, lupa, quickjs-ng-pypi with the required columns (wheels on 3 platforms, timeout, memory limit, output limit, release recency, build issues) and verified versions, a maintenance-risk row, an own-binding pricing row, rejected rows, and an os-sandbox row "not tested, not a gate candidate"

#### Progress
