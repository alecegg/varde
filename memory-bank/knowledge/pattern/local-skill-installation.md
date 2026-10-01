---
type: pattern
description: Varde installs shared skill copies under ~/.agents/skills and links selected harness skill directories to them.
generated: { by: codex/gpt-6, at: 2026-09-28T21:26:22Z }
paths:
  - varde
  - skills/install.sh
  - README.md
  - skills/README.md
---

- `varde sync` copies repository skills into `~/.agents/skills`, then links each selected harness's skills directory to those shared copies.
- `~/.agents/skills/<skill>` is a real installed directory; `~/.claude/skills/<skill>` and `~/.codex/skills/<skill>` may be symlinks to it. The repository's `skills/<skill>` is the source copied during sync.
- A harness `AGENTS.md` symlink into a shared agent-instructions file is a separate setup; the skills installer does not make that link.
