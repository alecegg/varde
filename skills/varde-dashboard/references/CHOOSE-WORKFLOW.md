# Option: Choose workflow

**Flow map.** Most work follows one path: `/varde-plan` drafts a living plan doc
and grooms terminology inline (and surfaces `## Open Questions`/`## Assumptions`
as the readiness answer), then grills the spec and decomposes it into tasks and
acceptance criteria → `/varde-build` executes one plan's tasks sequentially in
dependency order, detouring through `/varde-prototype` first when the plan
touches frontend/UI → `/varde-review` grades the diff against ACs and standards,
with `/varde-review-fix` resolving auto-fixable findings → the plan completes.
When the plan was split into a group of child plans, `/varde-orchestrate` runs
them all in dependency order, unattended, and does a single final merge. Two on-ramps skip straight into the middle
of this instead of starting at the top: "something's broken" enters at
`/varde-build posture=debug`; "the codebase needs behavior-preserving cleanup"
enters at `/varde-build posture=refactor`.

**Vocabulary layer.** Two references act as the single source of truth for
their vocabulary, reachable directly when the *words* are the problem
rather than the process: `/varde-knowledge` (write a `definition` note) for domain
vocabulary (glossary concepts), and `DESIGN-VOCABULARY.md` (referenced from
`/varde-review` and `/varde-plan`) for the deep-module design vocabulary
(module, interface, seam, depth, leverage, locality).

Present the following routing menu:

| Goal | Use |
|------|-----|
| Create plans, tasks, acceptance criteria, and scores after clarification | `/varde-plan` |
| Run all tasks in a selected plan (sequential, dependency order) | `/varde-build plan=<plan-id>` |
| Run a plan but defer completion and main merge | `/varde-build plan=<plan-id> finish=defer` |
| Choose a plan interactively and run it | `/varde-build` |
| Build a whole feature spanning multiple plans (a group plan) end to end | `/varde-orchestrate group=<plan-id>` |
| Review changed files, a target path, or a module direction | `/varde-review <target>` |
| Clarify intent, scope, terminology, and constraints | `/varde-plan` (grooms terminology inline; or `/varde-knowledge` for a standalone `definition` note) |
| Simplify code after review findings or explicit direction | `/varde-build posture=refactor` |
| Build or refine coding patterns | `/varde-knowledge` (write a `pattern`/`decision` note) |
| Consolidate what a chunk of work produced (friction + durable knowledge + a carry-forward handoff at a session boundary) | `/varde-reflect` |

Public skills (`plan`, `build`, `orchestrate`, `dashboard`, `review`) are
installed by default and available as slash commands.

Route the user to the correct skill — never execute the selected workflow
from `dashboard`.
