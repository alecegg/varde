# The growth loop

The plan file is a living document: seeded from the initial prompt
(`DRAFT-PLAN.md`), then *grown* section by section as understanding sharpens.
No gate to clear. A well-understood request starts near-final and grows
lightly; an ambiguous one starts rough with a long open list and grows more.

This file is the whole loop: *what* grows and the stance you bring
(sparring, routing unknowns, terminology, continuous audit), plus the
*per-turn mechanics* (watching the doc, resolving an item, exit criteria). It
all runs together every turn.

## What the doc holds

Each of these matures as the loop proceeds — none waits for a dedicated phase:

- Problem / Solution / Non-goals / Constraints
- Design (tech choices, schema, API/interface contracts)
- Plan-level acceptance criteria in GWT form — the contract of "done" for the
  whole change, at the same bar as `ACCEPTANCE-CRITERIA.md`'s review: testable,
  `Given`/`When`/`Then`, tagged assert/retrieve. Not per-task — task
  decomposition happens later, in `/varde-build`.
- `## Open Questions` and `## Assumptions` — the running record of what's
  still unresolved

Prefer research to guessing wherever an answer is verifiable rather than a
preference — read code, grep, `code_query`, or `varde-code`'s `context_pack`
for a keyword-driven sweep when `varde-code` is available (see
`references/VARDE-CODE-CLI.md`). Use `PLAN-FUNDAMENTALS.md`'s breadth-first
checklist so the sweep for unknowns stays thorough.

## Routing unknowns

Route anything you can't settle into the two persistent sections instead of
blocking:

- **`## Open Questions`** — anything turning on user preference, a tradeoff,
  or a fact nothing in the repo settles. One entry per question, in
  `INTERVIEW.md`'s live-question format including a recommendation (the user
  may answer by reading the doc alone, no chat round-trip):
  `- **<question>** — <why it matters>. Recommendation: <answer> — <reason>.`
- **`## Assumptions`** — anything guessed instead of asked so growth isn't
  blocked. One line: `<assumption> — affects: <plan split | AC | sequencing |
  design> — confidence: <low|medium|high>`.

A question inferable from code (even via a search) is research, not an Open
Question — only list it if the honest answer needs the user's preference or a
fact only they have.

**Ungrillable questions.** Some open questions can't be resolved by asking
more — the user must react to something concrete rather than describe it
(interaction feel, a state model or data shape that "feels right", a layout
tradeoff only visible once built). Mark these in `## Open Questions` by
appending `[needs prototype]`, then invoke `/varde-prototype plan=<plan-id>`
scoped to just that question. Resume growing with the prototype's answer once
that session closes.

## Sparring stance

You are a sparring partner while the doc grows, not a passive interviewer.
Assume build intent — the collaboration resolves *what* to build (and its
best-shaped version), not *whether*.

- **Give opinions, not just questions.** Say what's strong and why; call out
  what's weak, overcomplicated, or likely to cause trouble — part by part
  ("the X part is solid; I'd reconsider Y because Z"), not one pass/fail on
  the whole. If asked "is this a good idea?", answer directly before turning
  it back into a question.
- **Propose better shapes.** Offer alternatives or a better-shaped version
  when you see one, and say why it's better.
- **Hold to the smallest reasonable version.** Weigh whether the smallest
  version satisfying the concrete scenario is enough, or whether there's a
  real reason for more. Treat reuse / stdlib / native / existing-dependency /
  one-line candidates as guiding principles, not automatic stop conditions.
- **Stay at what/why/fit while sparring; go to specifics as the doc firms
  up.** Scope questions (is the problem real, direction, fit, boundaries) and
  implementation specifics (data models, file layout, signatures) both live
  in this one loop — but don't nail down signatures on a scope that's still
  moving.

**Rare "nothing to build".** If the concrete scenario turns out genuinely
speculative, or an existing capability fully covers it, don't stop
unilaterally — ask: "This looks like [X] already covers it — build anyway, or
is this a non-issue?" Only close as do-not-build on the user's explicit
agreement, then stop and discard the plan directory created in `DRAFT-PLAN.md`.

## Terminology and standards

Fold vocabulary and standards into the loop as they come up — surface them
early, once the Problem/Solution seed makes the domain concrete, and treat any
correction as an ordinary resolved item. Not a checkpoint to clear.

- **Terminology.** Grep for existing definitions (`RECIPES.md`, "Find
  terminology definitions", `type: definition` filter). If matches exist,
  surface them one line per term and ask whether they apply or any are stale,
  wrong, or missing. If none exist, groom the definition inline here (plan
  already grooms terminology) — or invoke `/varde-knowledge` to write a
  `definition` note — when there's genuinely vocabulary to establish; skip it
  when the domain language is already unambiguous.
- **Standards.** Grep for existing patterns (`RECIPES.md`, "Check for existing
  standards patterns"). If matches exist, surface them and ask whether any
  need adding or are stale. If none exist, invoke `/varde-knowledge` to write a
  `pattern`/`decision` note when there are standards worth establishing; skip it
  when nothing new applies.

Write each into `plan.md` as it settles (an ordinary resolving-an-item write),
not batched.

## Per-turn mechanics

The user resolves `## Open Questions` and `## Assumptions` however they prefer
— in chat, by editing the doc directly, or both, switching freely. Adapt to
whichever channel shows up; don't make the user restate a doc edit in chat.

**Watching the doc.** At the start of every turn, before responding, re-read
`plan.md` and diff it against the snapshot from the end of your last turn. Any
change to `## Open Questions`, `## Assumptions`, `## Design`, `## Non-goals`,
or `## Constraints` you didn't make yourself is a user edit — treat it exactly
like a chat answer: it can resolve a question, correct an assumption, or add
scope. Process doc edits and the chat message together in the same turn. Then
run the continuous audit below before responding.

**Resolving an item.** For each item resolved, whether via chat or a doc edit:

1. Update the matching `## Design` subsection (or `Non-goals`/`Constraints`)
   with the confirmed decision, in structured spec form per
   `assets/PLAN-TEMPLATE.md`'s writing-style rule.
2. Append one line to `## Decisions so far`: `<question> → <answer>`.
3. Remove the resolved line from `## Open Questions` or `## Assumptions`. A
   confirmed-as-is assumption now redundant with a `Decisions so far` entry is
   removed too — an explicitly accepted assumption graduates into a decision,
   it isn't kept as a separate open item.
4. Check whether the answer spawns new unknowns. It's normal for one resolved
   question to produce two more — add each as a new `## Open Questions` entry
   (same format, with a recommendation) rather than treating the list as
   something that should only shrink.

Edit the file immediately as each item resolves — don't batch to end of turn,
and don't wait for the whole list to clear before writing.

**Asking in chat.** Default to the doc as the surface for open items — leave
unresolved entries in `plan.md` for the user to resolve by editing, rather
than walking them one-by-one in chat. Switch to active 1-by-1 chat questioning
only when the user asks (e.g. "just ask me these one at a time"). Then follow
`INTERVIEW.md`'s question format and one-question-per-turn rule for that chat
message.

## Continuous audit

Auditing assumptions is a standing loop, not a one-shot. Every turn, as new
info arrives (chat or doc edit), re-scan what you've written:

- Implicit assumptions buried in Design/AC not yet in `## Assumptions`
  — add them with a calibrated confidence.
- Listed assumptions now miscalibrated given what was just learned — adjust.
- New unknowns the latest answer exposed — one resolved question routinely
  spawns two more; add them to `## Open Questions`.

Periodically (e.g. when a chunk of Design or Tasks firms up, or before
proposing the completeness gate) spawn a subagent to adversarially check
`## Assumptions` and `## Open Questions` for completeness — give it the current
`plan.md` and confirmed scope, and the instruction to find missed assumptions
and flag miscalibrated confidence. It returns a JSON list:
`{ item, kind: "missed_assumption"|"missed_question"|"miscalibrated",
location, note }`. Merge missed entries into the relevant section. This is the
same audit run as a deeper sweep; it doesn't replace the per-turn scan.

## Self-review before closing

Per `INTERVIEW.md`'s empty-queue rule, before proposing the completeness gate,
actively re-scan for gaps (see the re-scan-for-gaps rule in
`references/PLAN-FUNDAMENTALS.md`'s self-review checklist). If it surfaces
anything, add it as a new Open Questions entry and keep iterating.

## Exit criteria

Move to `PLAN-FUNDAMENTALS.md`'s Step 4 (metadata and closing) once:

- `## Open Questions` is empty (or every remaining line is explicitly `n/a`
  with a one-line reason).
- `## Assumptions` contains only items the user has actually seen and left
  unchallenged — not just items the author never revisited. If a long session
  has assumptions predating several rounds of unrelated back-and-forth,
  surface them once as a short batched list before treating them as accepted;
  don't let silence on an old line count as confirmation.
- The self-review scan above finds nothing new.
