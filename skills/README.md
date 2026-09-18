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
| `docs-cli` | Markdown knowledge storage and document watching |

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

## Skills

| Skill | Purpose |
|---|---|
| `varde-explore` | Explore problems, designs, code, and explanations |
| `varde-change` | Manage status, planning, building, verification, conclusion |
| `varde-review` | Report findings or explicitly improve reviewed code |
| `varde-docs` | Refresh user documentation or regenerate specifications |
| `varde-knowledge` | Maintain notes, reflection, friction, and handoffs |
| `varde-prototype` | Build throwaway visual or logic prototypes |
| `varde-agent-doc-authoring` | Author and audit agent-readable documents |

Natural language selects the correct mode automatically.
Explicit mode names remain useful in agent definitions.

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
