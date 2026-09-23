---
type: reference
description: Maps Varde user intents onto seven installed skills.
generated: { by: codex/gpt-5, at: 2026-09-17T13:45:19Z }
---

# Consolidated skill catalogue

Varde exposes seven user-facing skill packages.

- `varde-explore` investigates without planning or implementation.
- `varde-change` manages status, planning, execution, and conclusion.
- `varde-review` reports findings before explicit mutation modes.
- `varde-docs` refreshes documentation or regenerates specifications.
- `varde-knowledge` maintains notes, friction, reflection, and handoffs.
- `varde-prototype` builds throwaway visual or logic experiments.
- `varde-agent-doc-authoring` authors instructions consumed by agents.

Exploration transitions into change only after confirmation.
Review defaults to report-only behavior.
Standalone verification never mutates plan artifacts.
Handoffs appear only when work actually stops.

Worktree and `varde-code` behaviors remain internal techniques.
Each consuming skill carries synchronized local guidance copies.
