---
name: varde-plan
description: "Use this skill when the user wants to settle scope, design, assumptions, and acceptance criteria for a code change before it is built: a new idea, an unnamed draft, an unsettled request, or a resumed plan. It produces a reviewed plan with testable criteria and tasks ready to build."
recommends: [varde-prototype, varde-code]
---

# Settle scope before implementation

Use when scope or design is unsettled, including unnamed drafts. Planning owns no implementation.

- Never ask the user which mode to use. For dependent outcomes, draft a minimal plan, confirm once, then decompose before implementation.
- Ask one topic per turn as an inline numbered menu with a recommendation.
- Resolve `<working>` and `<knowledge>` with `varde setup paths --json`; never guess.
- Offer the draft as a served page and answer each comment.
- Read `references/plan.md`; it loads `references/plan-decomposition.md` when finalizing.
- Use `assets/PLAN-TEMPLATE.md` for plans and `references/TASK-TEMPLATE.md` for tasks.
