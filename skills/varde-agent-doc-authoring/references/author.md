# Author or revise an agent document

1. Read the target, `references/criteria.md`, and
   `references/specification.md`.
2. Gather evidence (criteria: Evidence and scope). Without a source or project
   context, a draft would only restate model defaults: offer a completed task
   or runbook, or ask one question at a time about:
   - the environment and tools actually used;
   - failures or near-misses and their fixes;
   - conventions a newcomer gets wrong;
   - steps done by hand or often forgotten.
3. After frontmatter edits, run `validate-frontmatter.py`.
4. Final pass on the changed files, short of the full review in
   `references/review.md`:
   - run `check-length.py` (criteria: Length limits)
   - after pointer or kind changes, run `skill-flow.py --write <skill-dir>` to
     refresh its FLOW.md
