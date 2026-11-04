---
topic: varde-skill-authoring/gather-evidence
version: 1
summary: Collect source material before drafting a skill
---

Without a source or project context, a draft would only restate model defaults. Ask for a completed task
or runbook, or ask one question at a time about:

- the environment and tools actually used;
- failures or near-misses and their fixes;
- conventions a newcomer gets wrong;
- steps done by hand or often forgotten.

Record only corrections the repository does not make obvious. Then read the target and `references/criteria.md`, and run `varde learn check <skill-dir>` and `varde learn check --write <skill-dir>` on the changed skill.
