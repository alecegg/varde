---
type: task
status: done
depends_on: [toz-scripting-count, toz-hook-spike, toz-script-runner-spike]
owns: [spikes/toz-report.md]
---

Evaluation report (non-blocking). Not measured. Write /Users/alec/source/varde-py/spikes/toz-report.md with: the scripting count and classification, the runner candidate table (numbers and pass/fail per row), hook latency and ioreg writes (previous baseline vs Python launch styles), a recommendation, and open risks. Then report it to the user; do not wait for approval (code-behavior check, ast-grep, packaging and worktree-writes may proceed in parallel).

#### Acceptance criteria

- assert: `test -s /Users/alec/source/varde-py/spikes/toz-report.md && test "$(grep -c -E '^## (Scripting count|Runner candidates|Hook latency and writes|Recommendation|Open risks)$' /Users/alec/source/varde-py/spikes/toz-report.md)" -eq 5` → exit 0

#### Progress
