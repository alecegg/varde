# Old learn migration goldens

These JSON snapshots were generated from the `learn` implementation at commit
`bab1ae6d` using a fresh `git archive` checkout. They record its SQLite rows,
legacy ID map, and exact `friction.jsonl` bytes for the matching migration
scenarios. Event generation used a fixed PID so the snapshots are reproducible.
`data/tests/test_friction_vs_learn.py` runs the current data implementation and
compares its results with these snapshots; it does not import the deleted learn
store modules.
