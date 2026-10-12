# varde agents

Installable subagent definitions for the `varde-*` workflow, shared across
harnesses. This folder is the **source of truth**. The `varde` CLI syncs the
right variant into each harness's agents directory alongside the
[`../skills/`](../skills/).

## Layout

Each agent is a folder holding one generated variant per harness:

```
agents/
  <name>/
    claude.md      # Claude Code — YAML frontmatter (name, description, tools, skills)
    codex.toml     # Codex — TOML (name, description, model, developer_instructions)
    opencode.md    # opencode 1.x — YAML frontmatter (mode: subagent, `permission:` map)
    opencode-v2.md # opencode 2+ — YAML frontmatter (mode: subagent, `permissions:` list)
    pi.md          # Pi (@tintinweb/pi-subagents) — YAML frontmatter (tools, model, prompt_mode, skills, allowed_subagents)
```

The four agents map onto the plan → execute → review lifecycle:

| Agent | Purpose | Backing skill(s) |
|---|---|---|
| `varde-planner` | Collaboratively scope a change | `varde-change plan` |
| `varde-builder` | Implement one bounded task and apply review fixes | `varde-change build`, `varde-review fix` |
| `varde-reviewer` | Report-only structured review | `varde-review report` |
| `varde-explorer` | Read-only repository navigation | `varde-explore` |

The agents invoke the `varde-*` skills by name through their harness; names such
as `varde-review report` refer to skill workflows, not shell executables. Their
CLI instructions use the `varde` command tree. Sync skills and agents together
with `varde setup sync` (see [`../skills/`](../skills/README.md)).

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

From the repository root, `just test-agents` runs this check and every test in `tests/`; `just test` runs all modules.

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

Install the `varde` CLI once, then sync skills and agents into canonical
directories:

```bash
cargo install --path ../clis/varde --locked --force
varde setup sync --skills-dir ~/.agents/skills --agents-dir ~/.agents/agents
```

Use `--harnesses <ids>` to select harnesses explicitly. Add one or more
`--instructions-target <file>` values to install the shared instruction block;
`--dry-run` previews the resolved setup without saving settings. The recommended
layout keeps one canonical copy in these directories and symlinks it into each
detected harness.

OpenCode adapters target V1 first: `opencode.md` uses the singular `permission:`
map (per-tool `allow`/`deny`; `task` allows only `varde-explorer` for planner,
builder, and reviewer and is denied for the explorer), and V1 documents the
plural `~/.config/opencode/agents/` discovery directory. When OpenCode 2+ is
detected, `varde setup sync --harnesses opencode` installs `opencode-v2.md`,
which uses the V2 `permissions` list (matching `subagent` rules). Detection
reads `VARDE_AGENTS_OPENCODE_VERSION` (for example `1.4.0`, `2.0.0`, or a bare
`2`), else `opencode --version`; an unknown version selects V1.

Pi agents (`pi.md`) target `@tintinweb/pi-subagents`. Each sets
`prompt_mode: replace` (no parent prompt or inherited `AGENTS.md`, so the body
tells the agent to read the repository's `AGENTS.md`), `skills: true` (inherits
the parent's skills, which include the Varde skills), no `model`
(`models.pi.model` is null, so agents inherit the main session's model), and
`tools` from `pi_tools`. Profiles whose `spawns` lists `varde-explorer` get
`allowed_subagents: varde-explorer`; the explorer, which spawns nothing, omits
it. The `varde-` prefix avoids collisions with harness built-in agents and user
agents.
