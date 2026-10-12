# eval-tools

Maintainer-only support for evaluations of skills under `skills/`. This
directory is not installed. The evaluation runners live in `varde-learn`
(`clis/learn/`); evaluation guidance is maintained in the installed skill's
[`references/evals.md`](../varde-learn/references/evals.md).

The commands are:

- `varde learn eval trigger <skill-name> <queries.json> --harness {claude,codex,opencode} [--runs N]` to measure description triggering.
- `varde learn eval output <skill-dir> [--harness {codex,claude}] [--model MODEL] [--judge-model MODEL] [options]` to compare skill-guided output with a no-skill baseline.

Output runs default to Codex `gpt-6-luna`; the judge inherits the selected model.
Claude requires explicit selection. Model/client failure never triggers fallback.
A run measures the selected harness/model only. Missing dollar-cost data means
unavailable, not free.

`eval output` copies `<skill-dir>` as-is; for a skill with entries in
`skills/shared/MANIFEST`, sync it to a temporary canonical directory first:
`HOME=<temp-dir>/home XDG_CONFIG_HOME=<temp-dir>/xdg VARDE_CONFIG_DIR=<temp-dir>/config CARGO_INSTALL_ROOT=<temp-dir>/cargo VARDE_TOZ_CONFIG_DIR=<temp-dir>/toz
varde setup sync --skills-dir <temp-dir>/skills
--agents-dir <temp-dir>/agents --harnesses none`. Point `<skill-dir>` at
`<temp-dir>/skills/<skill>`, not the repo directory.

`<skill-name>` and `<skill-dir>` resolve against `skills/` from anywhere in a
repository checkout.

Shared cross-skill query sets live in `query-sets/`. In particular,
`query-sets/sibling-boundaries.json` covers near-miss triggers between related
skills. Extract a target skill's entries and run them manually after changing
its description; the set is not wired into CI:

```sh
jq '[.[] | select(.target_skill=="<skill>") | {query, should_trigger}]' \
  query-sets/sibling-boundaries.json > "${TMPDIR:-/tmp}/query-set.json"
varde learn eval trigger <skill> "${TMPDIR:-/tmp}/query-set.json" --harness claude --runs 1
```
