# Distill working material

Entry: a concluded plan, or an area with no writes for 30 days, whose raw material is to be removed.

Outcomes:

- Keep as memory entries (`reference` concepts for area digests):
  - decisions and their reasons
  - designs or contracts missing from code
  - lessons and useful measurements
  - source links or IDs
- Drop progress, retries, review chatter, diffs, code-visible facts, and regenerable output.
- Limit a concept to 40 lines and a digest entry to 8.
- Leave alone plans that a non-terminal plan names in `depends_on`.
- Leave alone plans that kept material links, including `reviews/deferred/` and `distilled/`.
- Write drafts only after the user approves them.
- Bulk backfill needs user go-ahead and a verified snapshot, approved per batch of at most 10, oldest first.

Validation:

- `varde learn memory lint` has no errors (accept orphan-link warnings).
- `git status --short <memory root>` shows no unrelated edits before the commit.
- Commit concepts and digest entries together, by path.
- Confirm the off-machine snapshot before deleting the source directory; commit the deletion alone, by path.
