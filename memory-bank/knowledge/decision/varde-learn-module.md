---
type: decision
description: Friction capture, reflection, distillation, and skill evals move into a new learn-cli module with a varde-learn CLI and skill.
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-25T00:00:00Z }
---

## What
Create `learn-cli/` (binary `varde-learn`) plus a `varde-learn` skill that own friction, distillation, skill evals, and an adoption ledger, delivered as plan group `2026-09-25-varde-learn`: `eval-port` (scaffold, Rust port of `skills/eval-tools` runners) → `friction-store` (global SQLite store, friction commands, legacy import, `varde-workflow paths --learn`) → `skill-split` (skill out of `varde-knowledge` and `eval-tools`) → `adoption-ledger` (ledger, recurrence check). A post-skill friction check goes in `~/.agents/AGENTS.md`.

## Why
The working store is per project, so recurring skill friction never clusters across projects, evals cannot run outside this repo, and nothing measures whether a promoted fix worked.

## Constraints
- Do not collect or delegate session evidence during ordinary friction capture or evaluations. Only an explicit diagnosis request may pass bounded, source-linked evidence to one independent native analyst; never send a full transcript. In-session friction capture remains "check always, write only a real event," and executor subagents report friction to the orchestrator instead of writing it.
- Skill edits stay human-approved; evals launch paid sessions and run only on explicit approval.
- Name the ledger "adoptions", not "promotions" (`promotions/` holds plan promotion records).

## Related
- /decision/varde-learn-store-sqlite.md

## Current module behavior
- The Rust workspace is `clis/learn/`; it installs the `varde-learn` CLI and
  the `skills/varde-learn/` skill.
- `varde-learn diagnose inspect` reads bounded native session evidence and
  writes no friction data. `diagnose capture` records one eligible historical
  occurrence after its source witness and context are revalidated; it does not
  promote or resolve the friction item.
- Current-session aliases and unknown overlap require one independent analyst
  using native agent delegation. A saved normalized bundle preserves its
  original overlap assessment for the analyst. A new coordinator reusing the
  bundle must separately check trusted current identity against its target and
  family.
- Store schema 3 adds versioned incident provenance for captured occurrences.
  Existing rows remain compatible without fabricated keys. Version 1 Markdown
  exports include provenance when available, and imports preserve it; legacy
  imports remain unprovenanced.
- A missing native event ID may use only a verified append-stable JSONL line
  position and record digest. Rewritten, inherited, or uncertain event
  identity remains report-only.
