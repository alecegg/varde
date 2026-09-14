---
name: varde-plan
description: >
  TRIGGER: Start planning a new feature or change, or check readiness before
  building. Draft a living plan doc from the initial prompt, then grow it
  section by section — sparring on scope, auditing assumptions, and confirming
  terminology as you go — while the user steers by chatting or editing the doc
  directly, until the spec and acceptance criteria are complete. Then commit the
  plan. Asking "are we ready to build?" is answered here: the doc's open
  questions and assumptions are the readiness signal.
  SKIP: Skip when a ready plan should be executed or an existing change should be
  reviewed or fixed, or when small/ad-hoc work can go straight to /varde-build.
  Example phrases: "plan this feature", "define the acceptance criteria", or
  "are we ready to build?".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| *(feature idea given)* | Draft a new plan; run the workflow from step 1. |
| *(readiness question, e.g. "are we ready to build X?")* | Draft the doc from the idea and grow it far enough to surface `## Open Questions`/`## Assumptions` — those are the readiness answer. Continue into full planning if the user wants, or stop at the readiness snapshot. |
| *(no argument)* | Load `references/RESUME-PLANNING.md` and surface every draft plan awaiting a session (including stub child plans from a prior split) for the user to resume, instead of starting step 1. |

## Workflow

The spine is one continuous living-doc collaboration (steps 3–4): `plan.md` is
created from the initial prompt and grows section by section, with sparring,
auditing, and terminology folded into that same loop — not run as gates before
it. The plan settles the spec and the plan-level **acceptance criteria** (the
contract of "done"); it does **not** decompose into tasks — that happens later,
in `/varde-build`.

1. **Load references.** `references/RECIPES.md` (plan/task file conventions),
   `references/INTERVIEW.md` (chat-question format), and
   `references/GROW-DOC.md` (the living-doc loop — how the doc grows, the
   sparring/audit stance, terminology, and per-turn mechanics — used in
   steps 3–4). Plans and tasks are plain markdown, authored by editing
   files directly. Once per session, check whether the `varde-code` CLI (an optional tool, installed on PATH) is available: run `command -v varde-code >/dev/null 2>&1`. If present,
   load `references/VARDE-CODE-CLI.md` for optional blast-radius/dependents signal (used in
   `PLAN-FUNDAMENTALS.md`'s external-contract check and
   `ACCEPTANCE-CRITERIA.md`'s scope signals); otherwise use plain grep/read. Also
   check for the optional `varde-docs`/`docwatch` CLIs (`command -v varde-docs`); when present, load
   `references/VARDE-DOCS-CLI.md` — `varde-docs` gives the plan doc OCC-safe
   writes; `docwatch` enables in-doc collaboration mode (step 2). Both
   optional; without them, plan exactly as before.
2. **Choose the working location.** Work in the current checkout by default.
   It keeps the living plan visible for the user to inspect or edit at any
   time. Use `varde-worktree` only when the user requests isolation, a caller
   already owns a worktree, or concurrent edits create a concrete collision
   risk. State the reason before isolating. In-doc collaboration mode also
   uses the stable plan path. See `references/VARDE-DOCS-CLI.md`.
3. **Create and seed the doc, then hand off.** Full procedure:
   `references/DRAFT-PLAN.md`. Create `plan.md` from the initial prompt
   immediately — before asking anything — seeded with a best-guess
   understanding (Problem/Solution plus any inferable Design/Tasks/AC),
   routing unknowns into `## Open Questions`/`## Assumptions`. When
   `varde-docs` is present, create and grow the doc through it for OCC-safe
   writes (`references/VARDE-DOCS-CLI.md`); otherwise Write it directly. In
   in-doc collaboration mode, also register the doc's folder with `docwatch`
   now and seed the trigger-contract header, so the user can collaborate from
   the first turn (`references/VARDE-DOCS-CLI.md`). Tell the user the path and
   that it's theirs throughout — edit directly, chat, or both, in any order; a
   living doc, not an end-of-process review. This is a handoff notice, not a
   numbered question. If they say nothing or "continue," go to step 4.
4. **Grow the doc in a living loop.** The heart of the skill. Full procedure:
   `references/GROW-DOC.md` (how the doc grows, sparring/audit stance,
   terminology, and per-turn mechanics). Each turn: re-read `plan.md` for
   direct edits and process them together with the chat message; spar on
   scope, re-audit assumptions, fold in terminology/standards as they come up;
   write each resolution immediately. Plan-level acceptance criteria and the
   scope signals that shape them (`references/ACCEPTANCE-CRITERIA.md`) grow
   inline like any other section — task decomposition does not happen here.
   **Surface deferred review findings while sparring on scope.** Scope
   decisions belong here, not in build — so when the area under discussion has
   `Disposition: action-item` findings parked in `memory-bank/working/reviews/`
   (grep the category files for that disposition, match by the area/subsystem
   being planned, not by exact file — the plan has no file list yet), raise the
   relevant few for the user to fold into scope as acceptance criteria or leave
   deferred. Carry staleness context: name the review's date/branch and whether
   the area has changed since, so a finding predating the last refactor of this
   area isn't weighed as live. This is a surface-for-decision, not an
   auto-inclusion — the user decides; nothing is silently pulled in.
   Continue until `## Open Questions` and `## Assumptions` are
   both resolved (`GROW-DOC.md` exit criteria), then run `references/PLAN-FUNDAMENTALS.md`
   Step 4: confirm slug and UI surface, run the completeness gate, then the
   post-spec boundary check — the only point a multi-subsystem request splits
   (splitting before the spec exists is a guess this check would just redo).
5. **Finalize and commit the plan.** Run the acceptance-criteria review over the
   full criteria set (`references/ACCEPTANCE-CRITERIA.md`), check spec/AC
   consistency, surface autopilot's judgment calls, and commit `plan.md`. No task
   files are authored here. Full procedure: `references/PLAN-AUTHORING.md`.
6. **Resolve optional isolation.** When step 2 created a worktree, offer its
   merge and cleanup after the plan commit. Otherwise leave the committed plan
   in the current checkout.
7. **Reflect and consolidate.** Invoke `varde-reflect source=varde-plan` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

Write each decision to the doc the moment it resolves — never batch
(`GROW-DOC.md`'s resolving-an-item rule). Once step 4's completeness
gate confirms, enter **post-spec autopilot**: no more approval prompts,
revision confirmations, or assumption checks — except step 5's taste-decisions
gate (one batched review of close calls before commit). Stop only for a
malformed subagent result, a failed tool call, or a genuine contradiction in
the confirmed spec. If a call fails, report a hard error and stop.

## Gotchas

- Every question (sparring, terminology/standards, doc checkpoints, taste
  gate) uses `references/INTERVIEW.md`'s inline numbered-menu format, never a
  native question tool (e.g. `AskUserQuestion`). Its one-question-per-turn rule
  bounds only what you actively ask in chat — not what the user resolves by
  editing the doc between turns.
- The plan produces exactly one artifact: `plan.md`, carrying the spec and the
  plan-level `## Acceptance criteria`. It has no `## Tasks` section and no
  `tasks:` frontmatter array, and authors no task files — `/varde-build` creates
  `tasks/<task-id>.md` when it builds.
- This skill uses the current checkout by default. `varde-worktree` remains an
  opt-in isolation tool for a user request or a concrete concurrent-edit risk.
