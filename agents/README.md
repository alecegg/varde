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
    opencode.md    # opencode 1.x — YAML frontmatter (mode: subagent, `permission:` map)
    opencode-v2.md # opencode 2+ — YAML frontmatter (mode: subagent, `permissions:` list)
    pi.md          # Pi (@tintinweb/pi-subagents) — YAML frontmatter (tools, model, prompt_mode, skills, allowed_subagents)
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

```bash
./install.sh                       # all agents, Claude   -> ~/.claude/agents
./install.sh -t codex              # all agents, Codex    -> ~/.codex/agents
./install.sh -t opencode           # all agents, opencode -> ~/.config/opencode/agents
./install.sh -t pi                 # all agents, Pi      -> $PI_CODING_AGENT_DIR/agents, else ~/.pi/agent/agents
./install.sh -t claude -a varde-planner,varde-reviewer
./install.sh -t claude -d ./.claude/agents   # into a repo-local dir
```

Use `-m` for managed upgrades. It replaces only files carrying varde's
ownership marker and preserves same-named files created elsewhere. Use `-f`
only when every selected destination may be replaced explicitly.

Replacing a varde-managed agent keeps model settings you changed: `model` in
every harness (Pi included) and `model_reasoning_effort` for Codex. Values still equal to
varde's earlier default take the new default, and a key you deleted stays
deleted. Only these varde-shipped keys are tracked; other edits are replaced.
Each install appends `varde-default:` lines after the ownership marker to
record the shipped values, and renamed or legacy managed files carry their
settings over (`-n` prints `Would preserve user model setting`).
Pi agents ship no `model`, so a model you set is inserted after `description:`. A model
equal to the old Pi pin (`deepseek/deepseek-v4-flash`) counts as the old default and is
dropped, even if you chose it yourself.

On install each variant is renamed to the agent's canonical name for that
harness — `varde-executor/claude.md` → `varde-executor.md`, `varde-executor/codex.toml` →
`varde-executor.toml`, `varde-executor/opencode.md` (or `opencode-v2.md`) → `varde-executor.md`, `varde-executor/pi.md` → `varde-executor.md` — matching how each harness discovers agents
(Claude/Codex by the `name` field, opencode and Pi by filename).

Managed upgrades remove stale `build.<ext>` files from earlier releases.
The agents were renamed `explore`, `plan`, `review`, `executor` →
`varde-explorer`, `varde-planner`, `varde-reviewer`, `varde-executor`. With `-m` or
`-f`, installing a renamed agent also removes the old `<old>.<ext>` file when it
carries varde's ownership marker (`-n` prints `Would remove renamed managed`).
Unmanaged files remain byte-identical.

OpenCode adapters target V1 first: `opencode.md` uses the singular `permission:`
map (per-tool `allow`/`deny`; `task` allows only `varde-explorer` for planner, executor, and reviewer and is denied for the explorer), and V1 documents the plural
`~/.config/opencode/agents/` discovery directory. When OpenCode 2+ is detected,
`install.sh -t opencode` installs `opencode-v2.md` instead, which uses the V2
`permissions` list (matching `subagent` rules). Detection reads `VARDE_AGENTS_OPENCODE_VERSION` (for example
`1.4.0`, `2.0.0`, or a bare `2`), else `opencode --version`; an unknown version selects V1.
Pi agents (`pi.md`) target `@tintinweb/pi-subagents`. Each sets `prompt_mode: replace`
(no parent prompt or inherited `AGENTS.md`, so the body tells the agent to read the
repository's `AGENTS.md`), `skills: true` (inherits the parent's skills, which
include the Varde skills), no `model` (`models.pi.model` is null, so agents inherit the
main session's model), and `tools` from `pi_tools`. Profiles whose `spawns` lists `varde-explorer` get
`allowed_subagents: varde-explorer`; the explorer, which spawns nothing, omits it.
The `varde-` prefix avoids collisions with harness built-in agents and user
agents.

For the default OpenCode target, `-m` and `-f` remove a selected agent's managed
regular file from the legacy singular `agent/` directory only after installing
its replacement. Installing `varde-executor` also retires managed legacy `build.md`; old-named
legacy files (for example `plan.md`) are retired too.
Preserved destinations, unowned files, and symlinks do not trigger cleanup;
explicit `-d` targets never clean the global legacy directory. `-n` previews
these decisions without changing files.

OpenCode combines write and edit permission (`edit`). The reviewer's instruction to
write only review artifacts is therefore a prose scope restriction, not a hard
filesystem sandbox. Its shell permission remains broad enough to run review
checks and can also write files.
