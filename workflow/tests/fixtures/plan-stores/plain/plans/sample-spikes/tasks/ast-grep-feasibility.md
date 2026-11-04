---
type: task
status: done
depends_on: [repo-setup]
owns: [spikes/ast-grep/]
---

Not measured. Verify ast-grep-py on PyPI (version, wheels for aarch64-apple-darwin and x86_64/aarch64 linux) against the previous dependency ast-grep-core/ast-grep-language 0.45.1 (clis/code/crates/varde-code/Cargo.toml:13,20). Run a small sample of the repository's scan rules with previous and Python and compare match counts. State scan's proposed fate (port or drop; previous is not kept) for the gate.

#### Acceptance criteria

- assert: `test -s /Users/alec/source/varde-py/spikes/ast-grep/results/feasibility.md` → exit 0
- retrieve: `/Users/alec/source/varde-py/spikes/ast-grep/results/feasibility.md` → ast-grep-py version, wheels per target, match counts previous vs Python, proposed fate

#### Progress

