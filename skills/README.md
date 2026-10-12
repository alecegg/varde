# varde-skills

This module contains Varde's workflow, management, and tool skills.
Each installed package remains independently usable.

## Related modules

The `varde` binary provides local tooling. Skills use `varde setup` to resolve
memory paths; `varde map` is optional for code queries.

| Module | Purpose |
|---|---|
| `agents` | Installable plan, build, review, explore roles |
| [code module](../clis/code/README.md) | Structural code queries and scan rules |
| [workflow module](../clis/workflow/README.md) | Markdown knowledge storage and document watching |
| [learn module](../clis/learn/README.md) | Global friction storage and skill evaluations |
| [captured output module](../clis/toz/README.md) | Captured tool output and command batching |

## Install

Install the single `varde` CLI, then sync skills and agents into canonical
directories:

```bash
cd ../clis && cargo install --path varde --locked --force --target-dir target
varde setup sync --skills-dir ~/.agents/skills --agents-dir ~/.agents/agents
```

Pass one or more `--instructions-target <file>` values to install the shared
instruction block. Use `--dry-run` to preview the resolved setup without saving
settings, or `--harnesses <ids>` to choose harnesses explicitly. The recommended
layout keeps one canonical copy in `~/.agents/skills` and `~/.agents/agents`,
then symlinks those directories into detected harnesses.

Select a subset with `--skills <names>` or a preset (`--preset learn`,
`--preset scan`, `--preset workflow`, `--preset full`). With no flag and
nothing saved, sync installs every skill; `--skills all` resets a saved
selection.

## Skills

Each skill is a `SKILL.md` entry point plus a flat `references/` directory it
reads from on demand. Natural language selects the mode; explicit mode names
remain useful in agent definitions. Each `SKILL.md` is the authority for its
own rules — this map only says where to look.

- **`varde-explore`** — compares options or traces code, in chat or as a
  self-contained HTML explanation.
- **`varde-change`** — the change lifecycle: status, plan, build, verify,
  orchestrate a split plan, or fix a named bug evidence-first.
- **`varde-code`** — indexed source lookups through `varde map` for
  declarations, file relationships, and topic-based reading sets.
- **`varde-review`** — report findings read-only, apply a persisted review
  (fix), run visual QA, or tighten just-changed lines (simplify).
- **`varde-scan`** — run code scans, triage findings by severity, and persist
  decisions in a findings ledger.
- **`varde-docs`** — keeps `README.md`/`docs/` (refresh) or domain-first specs
  (spec) true to current code.
- **`varde-knowledge`** — durable memory: record or find knowledge notes, or
  wrap up learning and write session notes at a stopping point (reflect).
- **`varde-learn`** — record real friction, reconcile or distill recurring
  items, and maintain skill evaluations and trigger query sets.
- **`varde-prototype`** — a throwaway visual mockup or logic walkthrough that
  answers one design question.
- **`varde-agent-doc-authoring`** — writes and audits documents agents read,
  including these skills.
- **`varde-manage`** — installs and configures Varde and wires harness hooks.
- **`varde-customize`** — authors or tunes code scan rules and Toz output
  profiles or custom filters.
- **`varde-toz`** — retrieves captured tool output and batches commands through
  the Toz CLI. Varde installs this skill; the CLI installs capture adapters.

## Skill relations

`SKILL.md` frontmatter may declare two optional relations, each a list of
sibling skill directory names:

- `requires` — installed with the skill.
- `recommends` — a soft hint, never installed implicitly. Sync prints a
  one-line hint when a recommended skill is absent.

`varde setup sync` installs a selection's `requires` closure. `varde doc
frontmatter` errors on a relation that names an unknown skill, names the skill
itself, or forms a `requires` cycle. `varde-manage` is installed implicitly and
is never named in either list. Presets are named selections over the same
graph.

## Conventions they share

These conventions apply to the workflow skills. `varde-toz` documents the
standalone CLI operations it needs.

- **Memory locations.** Work in flight goes to `<working>/`; durable knowledge
  goes to `<knowledge>/`. Resolve both with `varde setup paths --json` and
  use its absolute paths. On failure, retry once with escalated access, then
  ask the user for the paths. A plan outside git cannot
  travel through a worktree, so those runs stay in the current checkout.
- **CLI use.** `varde setup` resolves memory paths. `varde map` sharpens code
  queries when `varde` is on `PATH`; each consuming skill states its fallback.
- **Work starts in the current checkout.** Parallel builder waves and refactor
  tasks use worktrees; a user can also request one. Whoever creates a worktree
  owns merging and removing it.
- **Questions are inline.** Numbered options, one topic per turn (related
  questions may be grouped), with a recommendation.
- **Friction and knowledge have separate owners.** Record real obstacles with
  `varde-learn`; record durable decisions and patterns with `varde-knowledge`.
  If `varde` is missing or a friction write fails, report that the event
  was not recorded and do not fall back to Markdown. Run Knowledge reflect only
  at a session boundary; it writes session notes only when work remains.

## Two SKILL.md shapes

Both are sanctioned. Pick by how much the skill branches, not by matching the
neighbours:

- **Dispatcher** — a 20–30 line `SKILL.md` that routes to one mode reference
  per row, each owning its own workflow. It earns the extra hop when modes are
  substantial and mutually exclusive, so a run loads one of them instead of
  all of them.
- **Inline** — the whole workflow lives in `SKILL.md`, references hold only
  phase detail. Right when the workflow is short and lightly branched; a mode
  layer there would be a hop to nothing.

Do not convert one shape to the other for consistency alone.

## Internal techniques

Worktree orchestration lives in `varde-change`
(`references/build-orchestrate-tasks.md`, `scripts/worktree-*.sh`) for isolated
writing tasks and explicit worktree requests.

Shared CLI references live once under `skills/shared/references/`. The
`skills/shared/MANIFEST` lists their consuming skills, and `varde setup sync`
copies each reference into those skills during installation. Edit the shared
source, not an installed copy. A shared file holds only content that
two or more skills use; `tests/shared-single-source.sh` fails when its text
also appears elsewhere. `tests/install-shared-files.sh` checks that installed
copies match the shared sources.

`tests/vendored-copies.sh` keeps the inlined memory-location paragraph aligned
across skills. It still pins that paragraph while CLI references use the
shared-file installer.

`skills/shared/references/review-gates.md` (the one-review rule) is shared by
`varde-agent-doc-authoring`, `varde-change`, and `varde-docs` through the same
manifest mechanism.

### Adding a review category

A new category is one more line in
`varde-review/references/report-categories.md`: its name, what to check, and
its severity calibration.

Run `./check-refs.sh` after editing references. It installs into a temp dir and
checks candidate backticked file paths and relative Markdown links. Bare paths
in prose or fenced commands are outside its pointer check.

## Benchmark checks

Run deterministic benchmark checks from the repository root:

```bash
skills/tests/benchmark-foundation.sh
```

The command runs every `tests/*.sh`, fails on any that is not executable, and
runs `check-refs.sh`. A new test needs no registration. It uses mock evaluation
responses and performs no billed evaluations.

## Change execution checks

Build strategies are `inline`, `parallel`, and `auto`. A `parallel` wave runs
two or three `varde-builder` subagents, each in its own worktree, on tasks that
`varde map blast_radius` shows are independent; everything else runs inline.
Tasks declare one testing profile and end with a prose evidence line.
Run the focused fixtures from the repository root:

```bash
skills/tests/parallel-wave-scheduler.sh
```
