# Python port follow-up backlog

Carry-over items from the Python port. Evidence paths below are final paths in the archived evidence tree (`projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/`) unless a plan note is named explicitly.

- Reconcile `python-tree.scan`: Python 187 findings vs Rust 335; complexity-gate 72 vs 192; hotspot 3 vs 56. Investigate comprehension roles and strict findings under tests. Source: `code-gate/report.md`; scan diagnosis and final counts: `code-gate/parity.md`.
- Finish rust-workspace scan diagnostics and `nav_map` entrypoint IDs; investigate the remaining 0-vs-1 flow difference. Source: `code-gate/parity.md` and `code-gate/report.md`.
- Resolve `symbol_blast_radius` unresolved-edge deltas. The code-gate report tracks this remaining parity item; mixed-fixture imports/edges also affect `context_pack` and `nav_map`. Source: `code-gate/report.md`; derived-table behavior: `code-index/derived-tables.md`.
- Revisit the index-speed gate before changing its verdict: cold 8.35x, no-change 8.82x, edit 8.04x slower than Rust. The gate verdict is conditional. Source: `code-gate/speed.md` and `code-gate/gate-report.md`.
- Deferred app-cli parity: `reexec.map_query` reports `not_found` before `index_missing`; `reexec.map_build` differs on `repos-py` vs `repos`. Keep the accepted-deviation output digest pinned. Source: `cutover/deferred-cases.md`.
- Continue perf-parallel follow-ups: profile entity/symbol/incremental work (including the incremental path), consider a persistent-process redesign, and reduce hook capture of 200 B from 92.5 ms toward the 80 ms gate. Free-threaded and Python 3.15 runs await wheels. Source: plan note `python-port-perf-parallel/notes/conclude-notes.md`; archived supporting reports: `perf-parallel/freethreaded.md`, `perf-parallel/py315.md`, `perf-parallel/hook-path.md`.
- Track the order-dependent `test_module_dispatch` failure: it fails when `test_cli_extract` imports `cli_extract` first. Source: plan note `python-port-perf-parallel/notes/conclude-notes.md`.
- Track the two pre-existing failing core `test_dependency_rules` tests. Source: plan note `python-port-perf-parallel/notes/conclude-notes.md`; package boundary authority: repository `python/varde-core/tests/test_dependency_rules.py`.
- Preserve the Kotlin `calls.kt` diagnostic as an acknowledged grammar variance; do not edit it as a parity fix. Source: `code-extract/parity-final.md`.
- Recheck mixed-fixture `context_pack`/`nav_map` and the `implements`/`imports` edge round. Source: `code-gate/report.md` and `code-index/derived-tables.md`.
- Complete the one-week dual-run signoff. Source: `cutover/signoff.md`.
- Run Linux execution testing; current archived gate evidence records Linux execution as deferred. Source: `code-gate/gate-report.md`; platform evidence: `core/linux-wheels.md`.
- Fix or document the root `justfile` `test` target masking per-package failures. Source: cleanup plan note `python-port-repo-cleanup/tasks/baseline.md` and the cleanup plan's repository test instructions.
