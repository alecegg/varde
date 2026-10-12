# Expected `executor` leftovers

Outside history (`reviews/`, `skills-audit-pass*`, `agent-doc-authoring-review-*`), `executor` remains only in:

- `clis/toz/crates/toz/src/machine.rs`: generic pipe executor.
- `clis/varde/src/sync/agents.rs`: the retired `varde-executor` name that sync removes.
- `clis/varde/tests/sync_agents_migration.rs`: retired-name cleanup and model-setting migration tests.
- `clis/workflow/md-core/src/memory.rs`: read fallback for a leftover `[orchestration].executors` key, and its test.
- `notes/allowed-leftovers.md`: this list.
