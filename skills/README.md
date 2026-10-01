# varde-skills

This module contains Varde's workflow, management, and tool skills.
Each installed package remains independently usable.

## Related modules

The sibling CLIs provide local tooling. Skills use `varde-workflow` to resolve
memory paths; `varde-code` is optional for code queries.

| Module | Purpose |
|---|---|
| `agents` | Installable plan, build, review, explore roles |
| `code-cli` | Structural code queries and scan rules |
| `workflow-cli` | Markdown knowledge storage and document watching |
| `learn-cli` | Global friction storage and skill evaluations |
| [toz-cli](../clis/toz/README.md) | Captured tool output and command batching |

## Install

Use `../varde sync` from the repository root to install or upgrade the skills
for every detected harness. It runs this installer for you.

Run the installer directly for manual setups. By default it copies every skill
into the shared `~/.agents/skills` directory, which no harness reads on its
own; link it into a harness with `-l`, or install elsewhere with `-d`:

```bash
./install.sh
./install.sh -d ~/.claude/skills -l ~/.agents/skills
./install.sh -d ~/.config/opencode/skills
./install.sh -s varde-change,varde-review
./install.sh -f
```

Run `./install.sh -h` for every available option.
`-n` checks current targets and link sources without writing or prompting. An
existing target without `-f` or `-m` is reported as conditional on confirmation;
a real run without a TTY would refuse that replacement.
A retired skill the installer placed, marked with `.varde-managed-skill` or
linked to the `-l` source, is removed automatically. Directories without that
marker are never touched.
Skill packages cannot contain symlinks, including in author-only files. The
installer-created `-l` link to a package is still supported.

## Skills

Each skill is a `SKILL.md` entry point plus a flat `references/` directory it
reads from on demand. Natural language selects the mode; explicit mode names
remain useful in agent definitions. Each `SKILL.md` is the authority for its
own rules — this map only says where to look.

- **`varde-explore`** — compares options or traces code, in chat or as a
  self-contained HTML explanation.
- **`varde-change`** — the change lifecycle: status, plan, build, verify,
  orchestrate a split plan, or fix a named bug evidence-first.
- **`varde-code`** — indexed source lookups for declarations, file
  relationships, and topic-based reading sets.
- **`varde-review`** — report findings read-only, apply a persisted review
  (fix), tighten just-changed lines (simplify), or triage `varde-code` rules
  (scan).
- **`varde-docs`** — keeps `README.md`/`docs/` (refresh) or domain-first specs
  (spec) true to current code.
- **`varde-knowledge`** — durable memory: record or find knowledge notes, or
  wrap up durable learning and handoffs at a stopping point (reflect).
- **`varde-learn`** — record real friction, reconcile or distill recurring
  items, and maintain skill evaluations and trigger query sets.
- **`varde-prototype`** — a throwaway visual mockup or logic walkthrough that
  answers one design question.
- **`varde-agent-doc-authoring`** — writes and audits documents agents read,
  including these skills.
- **`varde-manage`** — installs and configures Varde, authors scan rules and
  Toz output profiles, and verifies their loaded scope and tests.
- **`varde-toz`** — retrieves captured tool output and batches commands through
  the Toz CLI. Varde installs this skill; the CLI installs capture adapters.

## Conventions they share

These conventions apply to the workflow skills. `varde-toz` documents the
standalone CLI operations it needs.

- **Memory locations.** Work in flight goes to `<working>/`; durable knowledge
  goes to `<knowledge>/`. Resolve both with `varde-workflow paths --json` and
  use its absolute paths. On failure, retry once with escalated access, then
  ask the user for the paths. A plan outside git cannot
  travel through a worktree, so those runs stay in the current checkout.
- **CLI use.** `varde-workflow` resolves memory paths. `varde-code` sharpens
  code queries when on `PATH`; each consuming skill states its fallback.
- **Work starts in the current checkout.** Parallel executor waves and refactor
  tasks use worktrees; a user can also request one. Whoever creates a worktree
  owns merging and removing it.
- **Questions are inline.** Numbered options, one topic per turn (related
  questions may be grouped), with a recommendation.
- **Friction and knowledge have separate owners.** Record real obstacles with
  `varde-learn`; record durable decisions and patterns with `varde-knowledge`.
  If the Learn CLI is missing or a friction write fails, report that the event
  was not recorded and do not fall back to Markdown. Run Knowledge reflect only
  at a session boundary; it writes a handoff only when work remains.

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

Worktrees live only in `varde-change` (`references/build-worktree.md`,
`scripts/worktree-*.sh`), for parallel executor waves, refactor tasks, and
explicit requests.

Shared CLI references live once under `skills/shared/references/`. The
`skills/shared/MANIFEST` lists their consuming skills, and `skills/install.sh`
copies each reference into those skills during installation. Edit the shared
source, not an installed copy. A shared file holds only content that
two or more skills use; `tests/shared-single-source.sh` fails when its text
also appears elsewhere. `tests/install-shared-files.sh` checks that installed
copies match the shared sources.

`tests/vendored-copies.sh` keeps the inlined memory-location paragraph aligned
across skills. It still pins that paragraph while CLI references use the
shared-file installer.

The review-gate references and `risk-tier.py` instead have a single source
under `skills/shared/`, listed in `skills/shared/MANIFEST` (`<path> <skill>
...`). `install.sh` copies each into every skill its manifest row names, so
an installed skill is still self-contained; edit the file under
`skills/shared/`, not an installed copy.

### Adding a review category

A new category is one more heading in
`varde-review/references/report-categories.md`, which already defines the
evidence bar, the full-body sweep, and the auto-fix principle. State only what
is particular to the category, as bullets in this order:

| Bullet | Contents |
|---|---|
| When | One line: which changes trigger it, and when to skip it |
| Check | The one or two checks a reviewer would not think of unprompted |
| Severity | What moves a finding off its default for this category |
| Auto-fix | Optional: this category's exceptions to the general principle |

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
two or three `varde-executor` subagents, each in its own worktree, on tasks that
`varde-code blast_radius` shows are independent; everything else runs inline.
Tasks declare one testing profile and end with a prose evidence line.
Run the focused fixtures from the repository root:

```bash
skills/tests/parallel-wave-scheduler.sh
```
