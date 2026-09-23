# varde-skills

This module contains Varde's seven user-facing workflow skills.
Each installed package remains independently usable.

## Related modules

The sibling CLIs provide optional local tooling.
Skills fall back to ordinary file operations.

| Module | Purpose |
|---|---|
| `agents` | Installable plan, build, review, explore roles |
| `code-cli` | Structural code queries and scan rules |
| `workflow-cli` | Markdown knowledge storage and document watching |

## Install

Install every skill into Claude's default directory:

```bash
./install.sh
```

Choose another runtime directory or explicit subset:

```bash
./install.sh -d ~/.config/opencode/skills
./install.sh -s varde-change,varde-review
./install.sh -f
```

Run `./install.sh -h` for every available option.
Existing legacy directories receive one migration prompt.
Passing `--yes` approves their removal without prompting.

## Optional capability packs

The default install contains seven core skills. Optional packs are selected
explicitly and remain independent from the core catalogue:

```bash
./install.sh --pack browser
./install.sh --pack diagnostics
./install.sh --pack shipping
```

The browser pack installs `varde-browser` only. Direct selection also supports
optional skills:

```bash
./install.sh -s varde-browser
./install.sh -s varde-diagnose
./install.sh -s varde-release
```

Browser validation is report-only. If no supported browser tooling is on
`PATH`, it reports degraded capability and the checks that could not run. The
pack does not install browser tooling or release capability.

Diagnostics is report-only. It analyzes the current transcript by default,
requires fresh consent for historical sessions, and requires separate consent
for scrubbed exports. It does not install or modify production source.

Shipping prepares and verifies authorized releases. It installs no release
service or deployment tooling.

## Skills

| Skill | Purpose |
|---|---|
| `varde-explore` | Explore problems, designs, code, and explanations |
| `varde-change` | Manage status, planning, building, verification, conclusion |
| `varde-review` | Report findings or explicitly improve reviewed code; route risk-matched specialists |
| `varde-docs` | Refresh user documentation or regenerate specifications |
| `varde-knowledge` | Maintain notes, reflection, friction, and handoffs |
| `varde-prototype` | Build throwaway visual or logic prototypes |
| `varde-agent-doc-authoring` | Author and audit agent-readable documents |

Natural language selects the correct mode automatically.
Explicit mode names remain useful in agent definitions.

## Two SKILL.md shapes

Both are sanctioned. Pick by how much the skill branches, not by matching the
neighbours:

- **Dispatcher** — a 20–30 line `SKILL.md` that routes to one mode reference
  per row, each owning its own workflow. Used by `varde-change`, `varde-review`,
  `varde-docs`, `varde-knowledge`, `varde-explore`. It earns the extra hop when
  modes are substantial and mutually exclusive, so a run loads one of them
  instead of all of them.
- **Inline** — the whole workflow lives in `SKILL.md`, references hold only
  phase detail. Used by `varde-prototype` and `varde-agent-doc-authoring`. Right
  when the workflow is short and lightly branched; a mode layer there would be a
  hop to nothing.

`varde-explore` mixes both deliberately: explore mode is inline because it is
the default and nearly contentless, explain mode is a reference because it has
its own multi-step procedure and an artifact format.

Do not convert one shape to the other for consistency alone.

## Internal techniques

Worktree isolation and `varde-code` navigation are techniques, not skills.
Each consuming skill carries its own copy — `references/worktree.md`,
`references/varde-code.md` — plus `scripts/worktree-*.sh` where it needs them.

Edit the copy inside the skill that uses it. There is no shared source and no
sync step: a skill that cannot be copied on its own is the bug being avoided.

Most of each copy is meant to differ — every skill lists the operations it
actually uses. The shared contract is not, and a fix landing in one copy while
its siblings keep the old text is the failure mode this model invites.
`tests/vendored-copies.sh` pins the sections that must stay in step; add a
section to its manifest when a new one becomes contract.

Run `./check-refs.sh` after editing references. It installs into a temp dir and
fails on any pointer that would not resolve on a user's machine.

## Benchmark checks

Run deterministic benchmark checks from the repository root:

```bash
skills/tests/benchmark-foundation.sh
```

The command validates fixtures, changed-skill selection, and lifecycle schemas.
It uses mock evaluation responses and performs no billed evaluations.

## Change execution checks

Build strategies remain sequential by design.
Use `inline`, `fresh`, or `auto` execution selection.
Tasks declare profile-specific testing evidence.
Run the focused fixtures from the repository root:

```bash
skills/tests/change-execution-strategy.sh
skills/tests/change-testing-profiles.sh
```
