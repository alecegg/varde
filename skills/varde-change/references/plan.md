# Plan mode

## Where to start

| The request is | Start |
|---|---|
| A feature or change idea | Draft a new plan; run the workflow from step 1. |
| A readiness question — "are we ready to build X?" | Draft the doc from the idea and grow it far enough to show `## Open Questions` and `## Assumptions` — those are the readiness answer. Continue into full planning if the user wants, or stop at the readiness snapshot. |
| An ask to resume planning, with no idea named | Load `references/plan-resume.md` and show every draft plan awaiting a session, including stub child plans from a prior split, instead of starting step 1. |

## Workflow

Steps 3–4 use one shared plan document. Create `plan.md` from the initial prompt.
Update it section by section. Check scope, assumptions, and terminology as you
work. The plan settles the spec and the plan-level **acceptance criteria** (the
definition of done); it does **not** decompose into tasks — that happens later,
in `varde-change build`.

1. **Load references.** `references/plan-recipes.md` (plan/task file conventions),
   `references/plan-interview.md` (chat-question format), and
   `references/plan-grow-doc.md` (how to update the document, check scope and
   assumptions, and handle each turn — used in
   steps 3–4). Plans and tasks are plain markdown, authored by editing
   files directly. Load `references/varde-code.md` if that CLI is on PATH, for
   blast-radius and dependents signal. Load `references/varde-docs-cli.md` if
   `varde-docs` is — it gives the plan doc conflict-safe writes, and `docwatch`
   enables in-doc collaboration mode (step 2).
2. **Choose the working location.** Work in the current checkout by default.
   It keeps the plan visible for the user to inspect or edit at any
   time. Isolate per `references/worktree.md` only when the user
   requests it, a caller already owns a worktree, or concurrent edits create a
   concrete collision risk. Before creating a worktree, run
   `git check-ignore -q memory-bank/working/plans/.varde-change-plan-probe`. When it
   exits `0`, keep the plan in the caller checkout because Git cannot merge
   ignored plan files. When it exits `1`, worktree merge semantics apply.
   State the reason and storage mode before isolating. In-doc collaboration
   mode also uses the stable plan path. See `references/varde-docs-cli.md`.
3. **Create and seed the doc, then hand off.** Full procedure:
   `references/plan-draft.md`. Create `plan.md` from the initial prompt
   immediately — before asking anything — seeded with a best-guess
   understanding (Problem/Solution plus any inferable Design/Tasks/AC),
   routing unknowns into `## Open Questions`/`## Assumptions`. When
   `varde-docs` is present, create and grow the doc through it for conflict-safe
   writes (`references/varde-docs-cli.md`); otherwise Write it directly. In
   in-doc collaboration mode, also register the doc's folder with `docwatch`
   now and seed the trigger-contract header, so the user can collaborate from
   the first turn (`references/varde-docs-cli.md`). Tell the user the path, that
   you will work the open questions one at a time from here, and that the doc is
   theirs to read or edit at any point if they would rather answer there. This
   is a notice, not a numbered question — go straight into step 4's first
   question in the same turn.
4. **Update the document each turn.** Full procedure:
   `references/plan-grow-doc.md` (how the document changes, how to check scope and assumptions,
   terminology, and per-turn steps). Each turn: ask the highest-value open
   question in `references/plan-interview.md`'s format and wait; re-read
   `plan.md` for direct edits and process them together with the chat message;
   challenge the scope, re-check assumptions, add terminology/standards as they
   come up; write each resolution immediately. Only unknowns that need the user
   or are expensive to get wrong become questions — `references/plan-grow-doc.md`
   routes the confident low-impact ones to `## Assumptions` instead, shown as one
   batch at the exit check. It also covers the opt-in switch to doc-driven
   answering when the user asks for it. Plan-level acceptance criteria and the
   scope indicators that shape them (`references/plan-acceptance-criteria.md`) grow
   inline like any other section — task decomposition does not happen here.
   **Show deferred review findings during scope decisions.** Scope
   decisions belong here, not in build — so when the area under discussion has
   `Disposition: action-item` findings parked in `memory-bank/working/reviews/`
   (grep the category files for that disposition, match by the area/subsystem
   being planned, not by exact file — the plan has no file list yet), raise the
   relevant few for the user to add to scope as acceptance criteria or leave
   deferred. Carry staleness context: name the review's date/branch and whether
   the area has changed since, so a finding predating the last refactor of this
   area isn't weighed as live. This is a surface-for-decision, not an
   auto-inclusion — the user decides; nothing is silently pulled in.
   Continue until `## Open Questions` and `## Assumptions` are
   both resolved (`references/plan-grow-doc.md` exit criteria), then run `references/plan-fundamentals.md`
   Step 4: confirm the slug and UI work, run the final completeness check, then
   decide whether to split a multi-subsystem request
   (splitting before the spec exists is a guess this check would just redo).
5. **Finalize the plan.** Run the acceptance-criteria review over the
   full criteria set (`references/plan-acceptance-criteria.md`), check spec/AC
   consistency, show judgment calls made after confirmation, and mark `plan.md` ready for
   build. No task files are authored here. Full procedure:
   `references/plan-authoring.md`.
6. **Resolve optional isolation.** When step 2 created a worktree for tracked
   plan storage, offer its merge and cleanup after the plan is ready. Otherwise
   leave the ready plan in the current checkout.
7. **Reflect and consolidate.** Invoke `varde-knowledge reflect`, scoped to this
   run — it captures friction and collects any lasting knowledge the work
   produced. No handoff mid-session.

Write each decision to the document when it is made. Do not batch updates.
Once step 4's completeness check confirms, continue without more approval prompts,
revision confirmations, or assumption checks — except step 5's taste-decisions
check (one batched review of close calls before marking the plan ready). Stop only for a
malformed subagent result, a failed tool call, or a genuine contradiction in
the confirmed spec. If a call fails, report a hard error and stop.

## Gotchas

- Every question about scope, terminology, document checkpoints, or the taste
  check uses `references/plan-interview.md`'s inline numbered-menu format, never a
  native question tool (e.g. `AskUserQuestion`). Working the open questions down
  one per turn is the default; a doc edit the user makes between turns is an
  answer like any other and does not count against that turn's one question.
- The plan produces exactly one file: `plan.md`, carrying the spec and the
  plan-level `## Acceptance criteria`. It has no `## Tasks` section and no
  `tasks:` frontmatter array, and authors no task files — `varde-change build` creates
  `tasks/<task-id>.md` when it builds.
- Planning uses the current checkout by default. `references/worktree.md` is an
  opt-in isolation tool for a user request or a concrete concurrent-edit risk.
