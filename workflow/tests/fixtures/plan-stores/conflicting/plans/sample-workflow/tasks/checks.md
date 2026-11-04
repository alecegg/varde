---
type: task
status: todo
depends_on: [cli-and-help]
owns: [python/varde-workflow/tests/behavior check/**, python/varde-workflow/tests/fixtures/**]
---

Generate goldens with `uv run python -m test suite gen --module workflow --reference implementation /Users/alec/source/varde/clis/target/release/varde` (check the binary exists; cases use `args` with the reference implementation `plan`/`msg` prefix and `python_args` without it). Write `tests/behavior check/harness.py` with `prepare_case` for the throwaway git repo (execution-wave, check-task-ownership), watch first-N-frames and time/pid normalization, a fake `wake_command`. Cases for every command (incl. `--no-wake`, msg cursor files, `--handoff` warning) over fixture plan stores (plain, active plan set, conflicting ownership, concluded); cross-read plan files both ways.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run python -m test suite compare --module workflow` → exit 0 and last line `mismatches: 0`; run with `--min-cases 40` and one case group per command so none is uncovered

#### Progress
