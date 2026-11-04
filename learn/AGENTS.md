# Learn module guidance

Use `varde learn run --help` as the CLI contract.

- Supported UTC windows are `yesterday`, `since-last` (up to seven days), and
  `YYYY-MM-DD`.
- Coverage statuses include `pending`.

Run modes:

- `--no-model` writes deterministic metrics and a report without invoking the
  model.
- `--dry-run` makes no review-store writes.
- The learn-store lock serializes non-dry runs.

Preserve harness defaults unless the user disables them in
`~/.config/varde/learn/sources.toml`. Model review state is appended to
`reviewed.jsonl`; reports go to `reviews/<date>.md` under the resolved store.

When documenting runner scheduling, verify its defaults and budget API against
`runner/src/varde_runner/job_registry.py` and
`runner/src/varde_runner/web/jobs_route.py`.

## Subpackages

`learn` merges three former modules. `varde_learn.loop` holds session
diagnosis, friction, the learn store and guardrails. `varde_learn.docs` holds
skill checks, measures, how-topics, served pages and recap.
`varde_learn.knowledge` holds Concept CRUD, lint and discovery maps. Tests live
in `learn/tests/loop`, `learn/tests/docs` and `learn/tests/knowledge`.
`memory_dirs.py` stays in `core`. The `learn` install preset ships the learn
skills (`varde-learn`, `varde-diagnose`, `varde-improve`, `varde-knowledge`,
`varde-session-notes`, `varde-docs`, `varde-skill-authoring`,
`varde-doc-authoring`); the former `doc` and `knowledge` presets map to it.

## Command surface

Every command is `varde learn <concern> <verb>` at most; positionals do not
count. The old `varde doc` and `varde knowledge` groups and the flat learn
verbs are removed with no aliases. This table is the single source for docs and
the route test.

| Old command | New command | Subpackage |
| --- | --- | --- |
| `doc lint`, `doc frontmatter`, `doc flow --check` | `learn check <path>...` (`--write` regenerates stale FLOW.md; also validates a doc's blocks) | docs |
| `doc flow <dir>` | `learn measure <skill> flow` | docs |
| `doc flow ledger <action> <file>` | `learn measure <skill> ledger` | docs |
| `doc baseline status` | `learn measure <skill> baseline` | docs |
| `learn eval trigger`, `output`, `calibrate` | `learn measure <skill> trigger`, `output`, `calibrate` (billed; run only when named) | loop |
| `doc how <skill> [step]` | `learn how <skill> [step]` | docs |
| `learn how-report` | `learn skills demand [skill]` | loop |
| `doc spec inventory` | `learn docs spec` | docs |
| `doc serve`, `watch`, `comments`, `reply`, `recap` | `learn docs serve`, `watch`, `comments`, `reply`, `recap` | docs |
| `doc blocks` (`--check`) | `learn docs blocks [type]` (`--check` moves to `learn check <doc.md>`) | docs |
| `learn diagnose list`, `inspect` | `learn sessions show [session]` | loop |
| `learn diagnose summary`, `capture` | `learn sessions summary`, `learn sessions capture` | loop |
| `learn sweep`, `learn run` | `learn sessions sweep`, `learn sessions run` | loop |
| `learn calls`, `learn guardrails` | `learn sessions calls` (`--dead` filter) | loop |
| `learn guardrails fire <id>` | `learn sessions fire <id>` | loop |
| `learn adopt record`, `learn adopt recurrence` | `learn friction adopt`, `learn friction recurrence` | loop |
| `knowledge concept create\|show\|update\|set-field\|delete\|map` | `learn knowledge create\|show\|update\|set-field\|delete\|map` | knowledge |
| `knowledge concept list`, `knowledge concept search` | `learn knowledge search` (no filter lists) | knowledge |
| `knowledge lint` | `learn knowledge lint` | knowledge |

`learn friction list|add|show|set-status|export|import` and
`learn store ...` are unchanged. `learn knowledge map` writes the root and
per-type `index.md` files for a bundle (`--bundle`, default the resolved
knowledge directory). `varde setup paths` is unchanged. The `learn memory ...`
and `learn skills candidates|extract|reset|accept|reject|report` groups come
from sibling plans.

## Memory group

`learn memory` holds scoped memory and knowledge notes in one store (`docs/memory.md`).

- Each `learn knowledge <verb>` is a deprecated alias for `learn memory <verb>` (`create` is `add`) for one release. It prints a stderr notice and keeps the old JSON shape.
- Code is in `learn/src/varde_learn/memory/`; the pointer is `memory/surface.py`.
- The hooks are `app/src/varde/glue/memory_hook.py` (SessionStart) and `memory_subagent.py` (SubagentStart).
