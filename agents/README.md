# varde agents

Installable subagent definitions for the `varde-*` workflow, shared across
harnesses. This folder is the **source of truth**; `install.sh` deploys the
right variant into each harness's agents directory — the same install-based
model as [`../skills/`](../skills/).

## Layout

Each agent is a folder holding one generated variant per harness:

```
agents/
  <name>/
    claude.md      # Claude Code — YAML frontmatter (name, description, tools, skills)
    codex.toml     # Codex — TOML (name, description, model, developer_instructions)
    opencode.md    # opencode — YAML frontmatter (mode: subagent, per-tool permissions)
```

The four agents map onto the plan → execute → review lifecycle:

| Agent | Purpose | Backing skill(s) |
|---|---|---|
| `varde-planner` | Collaboratively scope a change | `varde-change plan` |
| `varde-executor` | Implement one bounded task and apply review fixes | `varde-change build`, `varde-review fix` |
| `varde-reviewer` | Report-only structured review | `varde-review report` |
| `varde-explorer` | Read-only repository navigation | `varde-explore` |

The agents invoke the `varde-*` skills by name through their harness; names such
as `varde-review report` refer to skill workflows, not shell executables. Install
the skills too (see [`../skills/install.sh`](../skills/install.sh)).

## Generation

`capabilities.json` is the semantic source of truth.
It defines profiles, skills, commands, and harness adapters.
Files under each profile directory are generated outputs.

Harness templates live under `templates/`.
They encode syntax without repeating profile instructions.

Regenerate committed variants:

```bash
./generate.py
```

Verify committed output byte-for-byte:

```bash
./generate.py --check
./test-consolidated-skills.sh
```

Verification regenerates into a temporary directory.
Every missing, unexpected, or stale path is reported exactly.

The default installed catalogue contains ten packages:

- `varde-explore`
- `varde-change`
- `varde-review`
- `varde-docs`
- `varde-knowledge`
- `varde-learn`
- `varde-prototype`
- `varde-agent-doc-authoring`
- `varde-manage`
- `varde-toz`

Agent instructions select modes within those installed packages.

## Install

```bash
./install.sh                       # all agents, Claude   -> ~/.claude/agents
./install.sh -t codex              # all agents, Codex    -> ~/.codex/agents
./install.sh -t opencode           # all agents, opencode -> ~/.config/opencode/agents
./install.sh -t claude -a varde-planner,varde-reviewer
./install.sh -t claude -d ./.claude/agents   # into a repo-local dir
```

Use `-m` for managed upgrades. It replaces only files carrying varde's
ownership marker and preserves same-named files created elsewhere. Use `-f`
only when every selected destination may be replaced explicitly.

On install each variant is renamed to the agent's canonical name for that
harness — `varde-executor/claude.md` → `varde-executor.md`, `varde-executor/codex.toml` →
`varde-executor.toml`, `varde-executor/opencode.md` → `varde-executor.md` — matching how each harness discovers agents
(Claude/Codex by the `name` field, opencode by filename).

Managed upgrades remove stale `build.<ext>` files from earlier releases.
The agents were renamed `explore`, `plan`, `review`, `executor` →
`varde-explorer`, `varde-planner`, `varde-reviewer`, `varde-executor`. With `-m` or
`-f`, installing a renamed agent also removes the old `<old>.<ext>` file when it
carries varde's ownership marker (`-n` prints `Would remove renamed managed`).
Unmanaged files remain byte-identical.

OpenCode adapters target V2, whose global discovery directory is plural
`~/.config/opencode/agents/`. V1 adapters are no longer generated. V2 uses
`permissions` fields rather than the legacy `tools` and `permission` mappings.
The `varde-` prefix avoids collisions with harness built-in agents and user
agents.

For the default OpenCode target, `-m` and `-f` remove a selected agent's managed
regular file from the legacy singular `agent/` directory only after installing
its replacement. Installing `varde-executor` also retires managed legacy `build.md`; old-named
legacy files (for example `plan.md`) are retired too.
Preserved destinations, unowned files, and symlinks do not trigger cleanup;
explicit `-d` targets never clean the global legacy directory. `-n` previews
these decisions without changing files.

OpenCode V2 combines write and edit permission. The reviewer's instruction to
write only review artifacts is therefore a prose scope restriction, not a hard
filesystem sandbox. Its shell permission remains broad enough to run review
checks and can also write files.
