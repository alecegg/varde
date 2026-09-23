## Phase 3: Propose edits for all docs

Process one document at a time by default. Delegate only independent documents,
with at most three delegates active. Each executor must:

1. Read the full document content.
2. Find the source files or specs to compare: use the marker's mapping if present;
   otherwise match by domain name — a doc named planning-and-build maps to the
   plan/build subsystem, architecture to the architecture layer, review to the
   review subsystem — and locate the corresponding source files or specs.
3. Read those sources in full.
4. Compare all hand-authored content (any section without a spec-declared marker
   block) with source facts. Flag differences: stale paths, removed or
   renamed skills or operations, contradicted invariants, missing concepts present
   in the source.
5. Produce a list of proposed changes: `{ section, current_text, proposed_text,
   rationale }`. If no divergences are found, reports "no changes proposed" for that
   doc.
6. For each unmarked doc, also propose a freshness marker (format:
   `references/refresh-marker-format.md`) identifying the source(s) that should track this
   doc going forward.

Group proposals by document. For each proposed change, show the
current text, the proposed replacement, and the rationale. The user approves or
skips each one.

Apply approved proposals by editing each doc in place. For each unmarked doc where the user approved
at least one change, prepend the proposed freshness marker as the first line of the
file.
