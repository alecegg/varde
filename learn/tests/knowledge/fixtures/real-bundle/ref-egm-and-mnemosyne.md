---
type: reference
status: current
date: 2026-11-01
---

# Reference: Elephant-Goldfish Model (Google) and Mnemosyne

Sources (user-provided 2026-11-01; read by a Haiku explorer through rendered pages only, not raw files or the API; not yet verified by a second reader):
- https://opensource.googleblog.com/2026/10/introducing-elephant-goldfish-model-plugin.html
- https://github.com/google/elephant-goldfish-model (linked from the blog)
- https://github.com/mnemosyne-oss/mnemosyne (also read `docs/README.md` and `docs/sync.md`)
- Not read: Mnemosyne Architecture and Memory Hygiene docs, EGM `docs/getting_started.md`, the Medium essay linked from the blog.

## Elephant-Goldfish Model (EGM)
- Apache-2.0 plugin for design and review with AI agents; "not an officially supported Google product"; the blog says thousands of Googlers use it daily (self-reported). Installs for Claude Code, Codex and Antigravity CLI.
- An "elephant" session keeps long-running context and writes no code. "Goldfish" sessions are stateless reviewers with zero context.
- Flow: `egm-brainstorm` writes `concepts_brief.md`, `egm-draft` writes `design_draft.md` (lists files to change) with feedback pauses, `egm-review` runs a comprehension check, an antagonistic review by several goldfish, and an implementation-readiness go/no-go. Other skills: `egm-resolve`, `egm-bootstrap`, `egm-review-loop`, `egm-drift-report`. Approved specs go to `docs/designs/`.
- Gate: review needs a session that can spawn fresh subagents; "If your agent cannot create them, EGM stops the review."
- State is only Markdown files. No memory data model.

## Mnemosyne
- MIT, local-first memory layer, one SQLite file; "BEAM" architecture: working memory (TTL eviction, auto-injected), episodic memory (sqlite-vec + FTS5 hybrid), TripleStore (temporal graph with `valid_from`/`valid_until`, `as_of` queries).
- Retrieval score: 50% vector, 30% FTS5, 20% importance, optional recency half-life (default 168 h). Binarized 48-byte embeddings with Hamming distance.
- Lifecycle: `remember`, `recall`, `sleep` (consolidates working into episodic). Forgetting is partial: `valid_until`, TTL, recency decay; conflict resolution tool is off by default.
- Sync: append-only `memory_events` log (CREATE/UPDATE/DELETE/CONSOLIDATE, `event_id` dedup, device id), HTTP pull/push, latest-wins conflicts, optional payload encryption; event metadata is not described as encrypted.
- Caveats: benchmark numbers (65.2% BEAM at 100K) were measured on v3.0.0 and not re-run; a LongMemEval figure was withdrawn for lack of a run log; RFCs (scope as tag namespace, text vs bytes) are proposals, not shipped.

## Ideas possibly useful to Varde (to discuss, none adopted)
1. Fresh-context design review as a gate in plan review: comprehension check, antagonistic critique, readiness check, and stop (do not silently weaken) when fresh agents cannot be created. Our plan reviews already use fresh reviewers; the comprehension and readiness checks and the explicit stop rule are the new parts.
2. Named artifact chain with approval pauses (brief, design, review) as a pattern for `varde-plan`.
3. Explicit scope on each memory entry (we already have it via directories); an append-only promotion event log with ids for dedup and audit as an alternative or addition to git-only promotion.
4. `valid_until` or expiry on memory and friction records so stale ones age out.
5. Benchmark honesty rule: label results with the version measured and when last re-run; withdraw numbers with no run log.
6. Avoid copying: vague forgetting, unrerun benchmarks, unencrypted sync metadata, no persistence beyond files in EGM.
