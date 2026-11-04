---
topic: varde-docs/spec-steps
version: 1
summary: Regenerate specs - part 1 of 2 (steps 1-2, find, generate)
---

# Regenerate domain specifications: steps 1-2

1. **Find domains needing updates:** run
   `varde learn docs spec --repository <repo-root> --knowledge <knowledge> --working <working> --json`
   and reuse its per-domain statuses and its `overlapping`, `unmatched`, and
   `unclassified_paths` inventory. Group the inventory's `missing` source
   directories into domains: one per workspace member/package, else one per
   top-level source directory with its own entry point. On a first run (no
   `index.md`), state the list.
2. **Generate domain documents** per `references/spec-format.md`, one at a
   time by default. Load `references/varde-code-cli.md`, and batch discovery and
   relationship queries per domain; use `get_symbol`/`batch` for exact bodies
   and related lookups. To delegate domains, see the `spec-delegation` topic
   (at most three active builders).

No missing or stale domain skips only step 2; continue with steps 3-6.
