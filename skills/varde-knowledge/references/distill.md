# Distill working material

Distill a concluded plan, or an area with no writes for 30 days, before
removing its raw material. Keep concepts in the `distilled` bundle under
`<working>`; resolve `<working>` with `varde setup paths --json`. The
`varde plan distill` output includes the bundle path.

## Keep the useful bits

Keep:

- decisions and their reasons;
- designs or contracts missing from code;
- lessons and useful measurements;
- source links or IDs.

Drop:

- progress, retries, and review chatter;
- diffs and code-visible facts;
- regenerable output.

Limit a concept to 40 lines and a digest entry to 8 lines.

## Distill and remove

1. Skip plans named by a non-terminal plan's `depends_on` or linked from kept
   material, including `reviews/deferred/` and `distilled/`.
2. For a plan, run `varde plan distill <plan-dir>` and use its read-only draft
   as a starting point. For other areas, list the source material manually.
3. Draft useful concepts and one short digest entry per area. Create concepts
   with `varde knowledge concept create --bundle <working>/distilled <slug>`;
   use `reference` concepts for area digests and append entries to the area's digest.
4. Present the drafts for user approval.
5. Lint with `varde knowledge lint --bundle <working>/distilled`; fix errors and accept orphan-link or missing-`index.md` warnings.
6. Before committing, `git status --short <working>` must show no unrelated edits. Commit approved concepts and digest entries together, by path.
7. Confirm the off-machine snapshot, then `git rm -r <dir>` and `rm -r` its leftovers. Commit the deletions alone, by path.

Bulk backfill needs user go-ahead and a verified snapshot; get approval per batch of at most 10, oldest first.
