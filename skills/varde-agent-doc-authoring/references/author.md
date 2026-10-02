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
3. After frontmatter edits, run
   `uv run scripts/validate-frontmatter.py <skill-dir>` (in a sandbox, prefix
   `UV_PYTHON_PREFERENCE=only-system`).
4. Final pass on the changed files, short of the full review in
   `references/review.md`:
   - run `scripts/check-length.py` (criteria: Scripts and length checks);
   - after any edit to a skill's files, run
     `scripts/skill-flow.py --write <skill-dir>` to refresh its FLOW.md.
