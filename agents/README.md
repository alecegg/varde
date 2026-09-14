# varde agents

Installable subagent definitions for the `varde-*` workflow, shared across
harnesses. This folder is the **source of truth**; `install.sh` deploys the
right variant into each harness's agents directory — the same install-based
model as [`../skills/`](../skills/).

## Layout

Each agent is a folder holding one variant file per harness:

```
agents/
  <name>/
    claude.md      # Claude Code — YAML frontmatter (name, description, tools, skills)
    codex.toml     # Codex — TOML (name, description, model, developer_instructions)
    opencode.md    # opencode — YAML frontmatter (mode: subagent, per-tool permissions)
```

The four agents map onto the plan → build → review lifecycle:

| Agent | Purpose | Backing skill(s) |
|---|---|---|
| `plan` | Collaboratively scope a change | `varde-plan` |
| `build` | Implement a ready plan; apply review fixes | `varde-build`, `varde-review-fix` |
| `review` | Report-only structured review | `varde-review` |
| `explore` | Read-only repository navigation | `varde-code-codebase-navigation` |

The agents reference the `varde-*` skills by name, so install the skills too
(see [`../skills/install.sh`](../skills/install.sh)).

## Install

```bash
./install.sh                       # all agents, Claude   -> ~/.claude/agents
./install.sh -t codex              # all agents, Codex    -> ~/.codex/agents
./install.sh -t opencode           # all agents, opencode -> ~/.config/opencode/agent
./install.sh -t claude -a plan,review
./install.sh -t claude -d ./.claude/agents   # into a repo-local dir
```

On install each variant is renamed to the agent's canonical name for that
harness — `build/claude.md` → `build.md`, `build/codex.toml` → `build.toml`,
`build/opencode.md` → `build.md` — matching how each harness discovers agents
(Claude/Codex by the `name` field, opencode by filename).
