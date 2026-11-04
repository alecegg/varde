---
topic: varde-diagnose/cycle-steps
version: 1
summary: Step order for a friction cycle over new sessions
---

1. Run `varde learn sessions summary --repository <ROOT> --harness all --new --limit N --mark` once (`N` is 1 to 10).
2. Trace every tool error and waste candidate to a specific session moment. Use `references/retro.md` for analysis and `varde learn friction list`/`add` (load the learn skill and follow its capture route) for deduplication and evidence format.
3. Capture observed friction:
   - Search with `varde learn friction list --text "<distinctive phrase>"` before adding; include the user's stated correction reason and keep one-offs in the analyzed-session ledger.
   - Tag patterns in 3+ sessions as `speed` or `token` with `--tag`, citing measured seconds or tokens; use `--item <ID> --tag <TAG>` for an existing item.
4. Triage with `varde learn friction show --brief <ID>...` and record supported transitions with `varde learn friction set-status <ID>... <STATUS> --reason "<evidence>"`.
5. Report sessions analyzed and items added or resolved, plus the top 3 waste patterns by tokens and cycle token totals. Propose improvements; express mechanical patterns as deterministic checks.
