---
type: task
status: done
depends_on: [repo-setup]
owns: [spikes/packaging/]
---

PyInstaller and PEX builds count as measured (shared lock, N>=5 where repeated).

Prove a multi-package uv workspace (varde-core, contracts package, varde-code, varde-toz, ...) mirroring clis/ crates and the rules in /Users/alec/source/varde/AGENTS.md, with check_deps.py and a --selftest. Cover:

- uv tool install with --with and extras
- entry-point plugin discovery of module subcommands
- varde setup sync and updates
- PyInstaller and PEX artifacts: macOS only, reuse the earlier sizes where valid; Linux artifacts documented, not built; Linux aarch64 install-and-run smoke test (container or CI runner) installs the package set with all 21 tree-sitter grammars and runs `varde --version`, a hook call, and a script-runner call that exceeds the timeout, memory limit and output limit and is stopped by each
- license row: SPDX of every dependency evaluated with the previous CI gate policy
- platform table for aarch64-apple-darwin, x86_64 and aarch64 linux (aarch64 linux installed and run, x86_64 by resolution or CI)

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py/spikes/packaging && uv run python check_deps.py && uv run python check_deps.py --selftest` → exit 0 (selftest exits 0 only when a deliberate violation fails)
- retrieve: `/Users/alec/source/varde-py/spikes/packaging/results/packaging.md` → install, --with/extras, plugin discovery, sync/update, per-target status, including the Linux aarch64 smoke test log (all 21 grammars installed; version, hook and limit-enforcement calls pass)
- retrieve: `/Users/alec/source/varde-py/spikes/packaging/results/licenses.md` → dependency, SPDX, pass/fail

#### Progress

