---
topic: varde-docs/docs-gotchas
version: 1
summary: Resolving working and knowledge paths without guessing
---

- Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`;
  retry once with escalated access, then ask; never guess. Outside a repo, use
  `mv`, not `git mv`.
- If you proceeded without a topic and failed, log friction with
  `--tag skilltrim --tag how-skip --source varde-docs`.
