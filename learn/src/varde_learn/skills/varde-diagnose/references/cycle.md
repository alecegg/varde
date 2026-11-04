<!-- kind: reference -->
# Friction cycle over new sessions

- `varde learn sessions summary --repository <ROOT> --harness all --new --limit N --mark` runs once (`N` is 1 to 10).
- Every tool error and waste candidate is traced to a specific session moment and analyzed per [`retro.md`](retro.md). Deduplicate each with `varde learn friction list --text "<distinctive phrase>"` before `friction add`, and include the user's stated correction reason. One-offs stay in the analyzed-session ledger.
- Patterns in 3+ sessions are tagged `speed` or `token` with `--tag`, citing measured seconds or tokens (`--item <ID> --tag <TAG>` for an existing item).
- Items are triaged with `varde learn friction show --brief <ID>...` and supported transitions recorded with `varde learn friction set-status <ID>... <STATUS> --reason "<evidence>"`.
- The report gives sessions analyzed, items added or resolved, the top 3 waste patterns by tokens, and cycle token totals. It proposes improvements and expresses mechanical patterns as deterministic checks.
