---
topic: varde-knowledge/distill-steps
version: 1
summary: Distill part 1 of 2 (steps 1-4) - draft and get user approval; write and delete in part 2
---

Resolve `<working>` and the memory root with `varde setup paths --json`.

Keep:

- decisions and their reasons
- designs or contracts missing from code
- lessons and useful measurements
- source links or IDs

Drop:

- progress, retries, and review chatter
- diffs and code-visible facts
- regenerable output

Limit a concept to 40 lines and a digest entry to 8 lines.

1. Skip plans that a non-terminal plan names in `depends_on` or that kept material links, including `reviews/deferred/` and `distilled/`.
2. For a plan, run `varde plan distill <plan-dir>` and use its read-only draft as a starting point. For other areas, list the source material manually.
3. Draft useful concepts and one short digest entry per area. Use `reference` concepts for area digests.
4. Present the drafts for user approval.
