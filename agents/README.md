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
| `plan` | Collaboratively scope a change | `varde-change plan` |
| `executor` | Implement one bounded task and apply review fixes | `varde-change build`, `varde-review fix` |
| `review` | Report-only structured review | `varde-review report` |
| `explore` | Read-only repository navigation | `varde-explore` |

The agents reference the `varde-*` skills by name, so install the skills too
(see [`../skills/install.sh`](../skills/install.sh)).

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

The default installed catalogue contains seven packages:

- `varde-explore`
- `varde-change`
- `varde-review`
- `varde-docs`
- `varde-knowledge`
- `varde-prototype`
- `varde-agent-doc-authoring`

Agent instructions select modes within those installed packages.

## Install

```bash
./install.sh                       # all agents, Claude   -> ~/.claude/agents
./install.sh -t codex              # all agents, Codex    -> ~/.codex/agents
./install.sh -t opencode           # all agents, opencode -> ~/.config/opencode/agent
./install.sh -t claude -a plan,review
./install.sh -t claude -d ./.claude/agents   # into a repo-local dir
```

Use `-m` for managed upgrades. It replaces only files carrying varde's
ownership marker and preserves same-named files created elsewhere. Use `-f`
only when every selected destination may be replaced explicitly.

On install each variant is renamed to the agent's canonical name for that
harness — `executor/claude.md` → `executor.md`, `executor/codex.toml` →
`executor.toml`, `executor/opencode.md` → `executor.md` — matching how each harness discovers agents
(Claude/Codex by the `name` field, opencode by filename).

Managed upgrades remove stale `build.<ext>` files from earlier releases.
Unmanaged files remain byte-identical.
