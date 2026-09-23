## Phase 2: Auto-generate spec-declared sections

For each doc identified in Phase 1 as having stale marker-declared sections,
regenerate each document one at a time by default. Delegate only documents whose
source and output paths do not overlap, with at most three delegates active.

Give each agent only:

- the document's current content;
- its docs marker (format: `references/refresh-marker-format.md`);
- the list of stale sources/sections to regenerate for that doc.

Rewrite only the listed marker-declared blocks. When `varde-code` was detected,
include its CLI path in the agent's prompt. Read short, known sources directly.
Batch Varde Code lookups for several files or relationships. Use `get_symbol`
only for exact symbols inside large files. Without `varde-code`, read directly
(Read/Grep/Glob, delegating only when another agent provides needed context).
Either way, write the replacement Markdown by hand. Preserve other marker
blocks and all hand-authored content. Then write the full document.

Map source content to Markdown as follows:

- Flow sections become prose steps followed by a Mermaid `flowchart` block.
- Architecture Layer Model and Dependency Constraints become exactly one
  combined Mermaid `graph` block.
- Key Operations, Invariants, and Acceptance Criteria remain prose only.

Use Mermaid fenced blocks that render on GitHub's native Markdown renderer.
