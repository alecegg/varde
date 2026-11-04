# eval-tools

Maintainer-only support for the `varde learn measure` runners. This directory is
not installed. For evaluation guidance run
`varde learn how varde-improve evals`.

The commands are:

- `varde learn measure <skill-name> trigger <queries.json> --harness {claude,codex,opencode} [--runs N]` to measure description triggering.
- `varde learn measure <skill-dir> output [--harness {codex,claude}] [--model MODEL] [--judge-model MODEL] [options]` to compare skill-guided output with a no-skill baseline.

Output runs default to Codex `gpt-6-luna`; the judge inherits the selected model.
Claude requires explicit selection. Model/client failure never triggers fallback.
A run measures the selected harness/model only. Missing dollar-cost data means
unavailable, not free.

`measure output` takes a directory path and copies it as-is. For repository skills
that use shared files, follow the sync steps in the evals guide above.

`measure trigger` takes a skill name used to identify trigger events. For Codex,
also pass `--skill-path` to the skill's `SKILL.md`. `measure output` takes an
explicit skill directory path; repository skills live in a module's `skills/` symlink or
`<module>/skills/`.

Shared cross-skill query sets live in `query-sets/`. In particular,
`query-sets/sibling-boundaries.json` covers near-miss triggers between related
skills. Extract a target skill's entries and run them manually after changing
its description; the set is not wired into CI:

```sh
jq '[.[] | select(.target_skill=="<skill>") | {query, should_trigger}]' \
  learn/eval-tools/query-sets/sibling-boundaries.json > "${TMPDIR:-/tmp}/query-set.json"
varde learn measure <skill> trigger "${TMPDIR:-/tmp}/query-set.json" --harness claude --runs 1
```
