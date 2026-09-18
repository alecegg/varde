# The growth loop

The plan file is seeded from the initial prompt (`references/plan-draft.md`),
then *grown* as understanding sharpens. A well-understood request starts
near-final and grows lightly; an ambiguous one starts rough with a long open
list and grows more. This whole file runs every turn.

## What the doc holds

Each matures as the loop proceeds.

- Problem / Solution / Non-goals / Constraints
- Design — tech choices, schema, API and interface contracts
- Plan-level acceptance criteria in Given/When/Then form, at the bar
  `references/plan-acceptance-criteria.md` sets: testable, tagged
  assert/retrieve. Not per-task — decomposition happens later, in build.
- `## Open Questions` and `## Assumptions` — what is still unresolved

Prefer research to guessing wherever an answer is verifiable rather than a
preference: read code, grep, or run `context_pack` when `varde-code` is available
(`references/varde-code.md`). Use `references/plan-fundamentals.md`'s
breadth-first checklist so the sweep stays thorough.

## Routing unknowns

Route anything you cannot settle into one of two persistent sections rather than
blocking. The sections are the record, not the queue you leave for the user —
you then work `## Open Questions` down one at a time in chat (per-turn steps
below).

**`## Open Questions`** — anything turning on user preference, a tradeoff, or a
fact nothing in the repo settles. One entry per question, in
`references/plan-interview.md`'s live-question format *including a
recommendation*, so the user can answer by reading the doc alone:
`- **<question>** — <why it matters>. Recommendation: <answer> — <reason>.`

**`## Assumptions`** — anything guessed instead of asked. One line:
`<assumption> — affects: <plan split | AC | sequencing | design> — confidence:
<low|medium|high>`.

A question inferable from code, even via a search, is research — not an Open
Question. List it only if the honest answer needs the user's preference or a fact
only they have.

**Which section an unknown lands in.** Two axes decide it — how confident you
are in the answer, and how much turns on being wrong:

- **Confident and low-impact** — you know the answer, and a wrong guess costs a
  contained rework inside one Design subsection. Write it as an `## Assumptions`
  line at `confidence: high` and keep going. It never costs a turn.
- **Everything else** — you are unsure, or the answer moves the plan split, the
  acceptance criteria, an external contract, or the shape of the solution. That
  is an `## Open Questions` entry, asked one per turn.

When the axes disagree, impact wins. A high-impact item you feel confident about
still earns its turn, because what is being weighed is the cost of being wrong,
not the odds of it.

**Some questions cannot be settled by asking.** The user has to react to
something concrete — interaction feel, a state model that "feels right",
a layout tradeoff only visible once built. Append `[needs prototype]`, invoke
`varde-prototype` scoped to that one question, and resume with its answer.

## Challenge the plan

You are a sparring partner, not a passive interviewer. Assume build intent: this
resolves *what* to build and its best-shaped version, not *whether*.

- **Give opinions, not just questions.** Say what is strong and why; call out
  what is weak, overcomplicated, or likely to cause trouble, part by part ("the X
  part is solid; I'd reconsider Y because Z") rather than one pass/fail verdict.
  Asked "is this a good idea?", answer directly before turning it back.
- **Propose better shapes** when you see one, and say why.
- **Hold to the smallest reasonable version** that satisfies the concrete
  scenario. Treat reuse, stdlib, native, existing-dependency, and one-line
  candidates as guiding principles, not automatic stop conditions.
- **Stay at what/why/fit early; go to specifics as the doc firms up.** Both share
  this one loop, but do not nail down signatures on a scope still moving.

**Rare "nothing to build":** If the scenario turns out genuinely speculative, or
an existing capability fully covers it, do not stop unilaterally — ask: "This
looks like [X] already covers it — build anyway, or is this a non-issue?" Close
as do-not-build only on explicit agreement, then discard the plan directory
`references/plan-draft.md` created.

## Terminology and standards

Fold these in early, once the Problem/Solution seed makes the domain concrete,
and treat any correction as an ordinary resolved item — not a checkpoint.

Grep for existing definitions and patterns (`references/plan-recipes.md`, "Find
terminology definitions" and "Check for existing standards patterns"). Show
matches one line each and ask whether they apply or are stale. With no matches,
groom a definition inline here or invoke `varde-knowledge` for a `definition`,
`pattern`, or `decision` note — but only when there is genuinely vocabulary or a
standard to establish; skip it when the domain language is already unambiguous.
Write each into `plan.md` as it settles, not batched.

## Per-turn steps

Drive the round in chat: ask the top open question, wait, write the answer in,
ask the next. The doc stays open as a second channel the user may use at any
time — a doc edit is an answer and counts as one — but it is not where you leave
work for them to find.

**Watch the doc.** At the start of every turn, before responding, re-read
`plan.md` and diff it against your snapshot from the last turn. Any change to
`## Open Questions`, `## Assumptions`, `## Design`, `## Non-goals`, or
`## Constraints` you did not make is a user edit — treat it exactly like a chat
answer. Process doc edits and the chat message together, then run the continuous
check before responding.

**Resolve an item**, by either channel: update the matching `## Design`
subsection (or `Non-goals`/`Constraints`) with the confirmed decision in
structured spec form per `assets/PLAN-TEMPLATE.md`'s writing-style rule; append
`<question> → <answer>` to `## Decisions so far`; remove the resolved line — an
explicitly accepted assumption graduates into a decision rather than staying an
open item; then check whether the answer spawns new unknowns. One resolved
question routinely produces two more, so add each as a new entry rather than
treating the list as something that should only shrink.

Edit the file the moment each item resolves, one at a time.

**Ask one question per turn.** This is the default for whatever the triage above
routed to `## Open Questions` — the items that need the user, or that are
expensive to get wrong. Take the highest-value one, ask it in
`references/plan-interview.md`'s inline numbered-menu format with your
recommendation, and wait.

Order by what unblocks the most: a question whose answer changes the shape of
the solution comes before one that picks between two spellings of the same
thing.

Batching happens at the triage, not here. Confident low-impact unknowns became
assumptions and are shown together at the exit check; they are never merged back
into a multi-question turn. Two questions in one turn splits the user's
attention across both and usually returns a clean answer to one of them.

**Doc-driven mode is opt-in.** When the user asks to work in the document —
"just put them in the doc", "I'll edit it directly", "stop asking" — switch:
leave entries in `## Open Questions` in the live-question format for them to
answer in place, and stop asking in chat until they ask you to resume. Say that
you have switched, so the change of surface is explicit rather than inferred
from a quiet turn.

## Continuous check

Every turn, re-scan what you have written for implicit assumptions in Design or
AC not yet listed (add them with a calibrated confidence), listed assumptions now
miscalibrated (adjust them), and new unknowns the latest answer exposed (add
them).

Periodically — when a chunk of Design firms up, or before the final completeness
check — spawn a subagent to adversarially check both sections for completeness.
Give it the current `plan.md` and confirmed scope, and the instruction to find
missed assumptions and flag miscalibrated confidence. It returns
`{ item, kind: "missed_assumption"|"missed_question"|"miscalibrated", location,
note }`. Merge missed entries in. This is the same check run as a deeper sweep;
it does not replace the per-turn scan.

## Exit criteria

Before proposing the final completeness check, re-scan for gaps per
`references/plan-fundamentals.md`'s self-review checklist; anything it surfaces
becomes a new Open Questions entry and the loop continues.

Move to `references/plan-fundamentals.md`'s Step 4 once:

- `## Open Questions` is empty, or every remaining line is explicitly `n/a` with
  a one-line reason.
- `## Assumptions` contains only items the user has actually seen and left
  unchallenged — not items the author never revisited. Because the triage routes
  every confident low-impact unknown here without asking, show the whole list
  once, as a short batch, before treating any of it as accepted: one line each,
  grouped by what they affect, with the high-impact ones first. Silence on a
  line the user never saw is not confirmation. This is the one place batching
  belongs, and it is a single turn no matter how many lines it carries.
- The self-review scan finds nothing new.
