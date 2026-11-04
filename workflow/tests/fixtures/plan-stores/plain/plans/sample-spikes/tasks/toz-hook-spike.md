---
type: task
status: done
depends_on: [repo-setup]
owns: [spikes/toz-hook/]
---

Steps:

- Measured (shared lock, N>=5 and the p50/p95 run counts below).
- First step: measure the previous baseline from the read-only /Users/alec/source/varde build (a measurement only, not a dependency of the port); record its p95 before any threshold is computed.
- Measure a Python `varde capture --hook` that does equal work to previous `varde run capture --hook --harness claude-code` (same captured row count and stdout shape per payload from clis/benches/toz-hook.sh, which takes --binary and --command so both share one runner): p50/p95 over >= 30 runs, cold and warm, `uv run` vs installed entry point, `-X importtime` breakdown, ioreg over a window of K calls vs a matched idle window.
- Also check sqlite FTS5 porter and trigram in uv-managed Python and glob-to-regex behavior check against the profile.rs tests (not measured; may run now).
- Write results/hook.json, validate.py, check.sh (with --mutate self-test).

#### Acceptance criteria

- assert: `python3 /Users/alec/source/varde-py/spikes/toz-hook/validate.py` → exit 0 (schema, cold/warm, runs >= 30, equal row count)
- assert: `/Users/alec/source/varde-py/spikes/toz-hook/check.sh && /Users/alec/source/varde-py/spikes/toz-hook/check.sh --mutate` → exit 0 (second exits 0 only when the mutated case fails)

#### Progress

