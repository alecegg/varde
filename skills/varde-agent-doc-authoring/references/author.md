# Author or revise an agent document

1. Read the target, `references/criteria.md`, and
   `references/specification.md`.
2. Gather evidence (criteria: Evidence and scope). Without a source or project
   context, a draft would only restate model defaults: ask for a completed task
   or runbook, or ask one question at a time about:
   - the environment and tools actually used;
   - failures or near-misses and their fixes;
   - conventions a newcomer gets wrong;
   - steps done by hand or often forgotten.
3. Run `varde doc lint <skill-dir-or-file>`, `varde doc frontmatter <skill-dir>`, and `varde doc flow --write <skill-dir>` on the changed skill.
