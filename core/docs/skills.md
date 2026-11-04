# varde-skills

This module contains most of Varde's workflow, management, and tool skills.
Each installed package remains independently usable.

## Related modules

The `varde` binary provides local tooling. Skills use `varde setup` to resolve
memory paths; `varde map` is optional for code queries.

| Module | Purpose |
|---|---|
| `agents` | Installable plan, build, review, explore roles |
| [code module](../../code) | Structural code queries and scan rules |
| [workflow module](../../workflow) | Plans, tasks, messages, plan watching, and the change and review skills |
| [learn module](../../learn) | Global friction storage and skill evaluations |
| [captured output module](../../toz) | Captured tool output and command batching |

## Install

Install the single `varde` CLI, then sync skills and agents into canonical
directories:

```bash
uv tool install --force --from ./app varde
varde setup sync --skills-dir ~/.agents/skills --agents-dir ~/.agents/agents
```

Pass one or more `--instructions-target <file>` values to install the shared
instruction block. Use `--dry-run` to preview the resolved setup, or
`--harnesses <ids>` to choose harnesses explicitly. Sync flags apply to that run
only; add `--save` to persist them as defaults (`--save --dry-run` does not
write). The recommended layout keeps one canonical copy in `~/.agents/skills`
and `~/.agents/agents`, then symlinks those directories into detected harnesses.

Select a subset with `--skills <names>` or a module preset (`--preset toz`,
`--preset code`, `--preset learn`,
`--preset dev`, `--preset workflow`, `--preset full`). With no flag and
nothing saved, sync installs every skill; `--skills all` selects every skill
for that run.

## Skills

Each skill is a `SKILL.md` entry point plus a flat `references/` directory it
reads from on demand. Natural language selects the mode; explicit mode names
remain useful in agent definitions. Each `SKILL.md` is the authority for its
own rules — this map only says where to look.

- **`varde-explore`** — compares options or traces code in chat.
- **`varde-explain`** — explains code or options in chat or as a self-contained
  HTML page.
- **`varde-pr`** — writes a pull request description with its summary, evidence,
  and merge danger.
- **`varde-plan`**, **`varde-build`**, and **`varde-orchestrate`** — plan
  unsettled work, implement one bounded task, or coordinate several tasks in one
  plan.
- **`varde-swarm`** — opt-in: runs several plans in parallel with one
  orchestrator each, only when the user explicitly asks; with no arguments it
  reports status.
- **`varde-code`** — indexed source lookups through `varde map` for
  declarations, file relationships, and topic-based reading sets.
- **`varde-review`** — report findings read-only, apply a persisted review
  (fix), or tighten just-changed lines (simplify).
- **`varde-review-ui`** — visual QA and persona audits of a running UI.
- **`varde-verify`** — verifies finished work without changing it.
- **`varde-scan`** — run code scans, triage findings by severity, and persist
  decisions in a findings ledger.
- **`varde-docs`** — keeps `README.md`/`docs/` (refresh) or domain-first specs
  (spec) true to current code.
- **`varde-knowledge`** — durable memory: record or find knowledge notes, or
  wrap up learning at a stopping point (reflect).
- **`varde-session-notes`** — write, snapshot, or resume session notes.
- **`varde-learn`** — record real friction, reconcile items, and check whether
  a fix recurred.
- **`varde-diagnose`** — diagnose sessions and run friction retrospectives.
- **`varde-improve`** — distill recurring friction into improvements and
  maintain skill evaluations and trigger query sets.
- **`varde-prototype`** — a throwaway visual mockup or logic walkthrough that
  answers one design question.
- **`varde-skill-authoring`** — writes, minimizes, and audits skills and agent
  documents.
- **`varde-doc-authoring`** — writes and audits other documents agents read
  (AGENTS.md, specs, criteria).
- **`varde-manage`** — installs and configures Varde and wires harness hooks.
- **`varde-customize`** — authors or tunes code scan rules and Toz output
  profiles or custom filters.
- **`varde-toz`** — retrieves captured tool output and batches commands through
  the Toz CLI ([source](../../toz/skills)). Varde installs this skill; the CLI
  installs capture adapters.

## Skill relations

`SKILL.md` frontmatter may declare two optional relations, each a list of
sibling skill directory names:

- `requires` — installed with the skill.
- `recommends` — a soft hint, never installed implicitly. Sync prints a
  one-line hint when a recommended skill is absent.

`varde setup sync` installs a selection's `requires` closure. `varde learn check`
errors on a relation that names an unknown skill, names the skill
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

Worktree orchestration lives in `varde-orchestrate`
(`references/build-finish.md`, `varde learn how varde-orchestrate dispatch`, `scripts/worktree-*.sh`) for isolated
writing tasks and explicit worktree requests.

Shared CLI references live in `varde-core`'s `skills/shared/`: `MANIFEST` and
`references/`. The manifest lists consuming skills, and `varde setup sync`
copies each reference into those skills during installation. Edit the shared
source, not an installed copy. `app/tests/install-shared-files.sh` checks that
installed copies match the shared sources.

`varde-core`'s `skills/shared/references/review-gates.md` (the one-review rule) is shared by
`varde-skill-authoring`, `varde-doc-authoring`, the workflow tier skills, and `varde-docs` through the same
manifest mechanism.

### Adding a review category

A new category is one more line in
`varde-review/references/report-categories.md`: its name, what to check, and
its severity calibration.

Run `./core/scripts/check-refs.sh` after editing references. It installs into a temp dir and
checks candidate backticked file paths and relative Markdown links. Bare paths
in prose or fenced commands are outside its pointer check.

## Shell test checks

Run the shell tests from the repository root:

```bash
just test-shell        # all tiers
just test-shell fast   # the fast tier that `just test` runs
```

`core/scripts/run-shell-tests.sh` runs every `*/tests/**/*.sh` in an isolated environment (named
helpers are skipped) and fails on any runnable script missing from
`core/scripts/shell-test-tiers.txt`. `check-refs.sh` runs separately. The app
shell checks also run through `uv run pytest app/tests`. The checks use mock
evaluation responses and perform no billed evaluations.

## Change execution checks

Build strategies are `inline`, `parallel`, and `auto`. A `parallel` wave runs
two or three `varde-builder` subagents, each in its own worktree, on tasks that
`varde map blast_radius` shows are independent; everything else runs inline.
Tasks declare one testing profile and end with a prose evidence line.
Run the focused fixtures from the repository root:

```bash
workflow/tests/parallel-wave-scheduler.sh
```
