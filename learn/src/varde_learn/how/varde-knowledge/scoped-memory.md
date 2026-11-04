---
topic: varde-knowledge/scoped-memory
version: 1
summary: Add, list, show, retire, and promote scoped memory lessons
---

Short lessons loaded at session start, in four scopes:

- `agent`: one agent (key: its name, such as `varde-builder`). It needs `--model` and `--harness-version`. Read it with `varde learn memory surface --agent <name>`.
- `skill`: one skill (key: skill name).
- `project`: one project (key: project key; default is the current project).
- `global`: everywhere (no key).

Commands:

- `varde learn memory add --scope <scope> [--key <k>] --text "<lesson>"` (secrets are rejected).
- `varde learn memory list [--scope <s>] [--skill <name>]`.
- `varde learn memory show <id>`.
- `varde learn memory retire <id>`.

Workflow: SessionStart shows a pointer and index lines, never bodies. When it prints `Skill memory: <skills>`, run `varde learn memory list --skill <name>` before using a listed skill, then `show <id>` only for lines that apply.

Review before share:

- `promote` commits to a local branch of the shared checkout and never pushes.
- A person reviews the text for secrets and project-specific detail, then pushes and opens the review.
- Project-scope entries cannot be promoted. Shared entries change only by reviewed commit.
