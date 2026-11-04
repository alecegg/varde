---
topic: varde-knowledge/distill-write
version: 1
summary: Distill part 2 of 2 (steps 5-7) - write user-approved drafts; snapshot before delete
---

# Distill: write and remove

5. Write each approved draft with `varde learn memory add --scope project --no-surface --json --text`
   and set its `type` with `memory set-field <id> type <t> --expected-version <v>`
   (`v` is the `version` from `add`); append to an area's digest with
   `memory update`. Run `varde learn memory lint`; fix errors and accept orphan-link warnings.
6. Before committing, `git status --short <memory root>` must show no unrelated edits. Commit approved concepts and digest entries together, by path.
7. Confirm the off-machine snapshot, then `git rm -r <dir>` and `rm -r` its leftovers. Commit the deletions alone, by path.

Bulk backfill needs user go-ahead and a verified snapshot. Get approval per batch of at most 10, oldest first.
