---
type: reference
status: stable
---

# Workflow conclusion

`varde plan conclude <dir> [--merged <rev>] [--repo <path>]` is the only
conclusion gate. It reads `<dir>/review.md` and succeeds only when both hold:

- the report's `verdict` is `approved`;
- the merged commit equals the report's `head`.

The repository is `--repo <path>` when given, else the git root of the cwd.
`--merged <rev>` overrides the commit compared with `head` (default `HEAD`).
On success in a plan directory the plan's `status` becomes `completed`.
Otherwise it exits 1 naming the verdict or both shas, or
`review commit <sha> not found in <repo>`.

No other review machinery gates conclusion: there are no subjects, fingerprints,
records, contracts, or checkpoints. The report header (`verdict`, `reviewer`,
`base`, `head`) written by the independent review IS the gate. A fixes-only
re-review or header-only re-check rewrites `head`, so `head` always covers every
commit merged before conclusion.

`varde plan status` and `varde plan now` remain advisory: they print a
staleness notice per plan when `git log <reviewed_commit>..HEAD` touches the
plan's `owns` paths (or `shared:` when a plan has no `owns`) or
`reviewed_on` is over 7 days old, and they never exit non-zero for it.