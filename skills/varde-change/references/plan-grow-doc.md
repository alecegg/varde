# The growth loop

Seed the plan file from the initial prompt (`references/plan-draft.md`), then
update it as understanding sharpens. A well-understood request may start
near-final and need few updates. An ambiguous request starts rough and needs
more updates. Run this procedure every turn.

## What the doc holds

Update each section as the loop proceeds.

- Problem / Solution / Non-goals / Constraints
- Design — tech choices, schema, API and interface contracts
- Plan-level acceptance criteria in Given/When/Then form, at the bar
  `references/plan-acceptance-criteria.md` sets: testable, tagged
  assert/retrieve. Not per-task — decomposition happens later, in build.
- `## Open Questions` and `## Assumptions` — what is still unresolved

Research whenever the repository can answer a question. Read code, grep, or run
`context_pack` when `varde-code` is available (`references/varde-code.md`). Use
the breadth-first checklist in `references/plan-fundamentals.md` to cover the
full scope.

## Routing unknowns

Put every unsettled item in one of two persistent sections instead of blocking.
These sections record the work; they are not a queue to leave for the user.
Resolve `## Open Questions` one at a time in chat (see the per-turn steps below).

**`## Open Questions`** — Use this section for user preferences, tradeoffs, or
facts the repository does not settle. Add one entry per question, in
`references/plan-interview.md`'s live-question format *including a
recommendation*, so the user can answer by reading the doc alone:
`- **<question>** — <why it matters>. Recommendation: <answer> — <reason>.`

**`## Assumptions`** — Use this section for anything guessed instead of asked.
Write one line:
`<assumption> — affects: <plan split | AC | sequencing | design> — confidence:
<low|medium|high>`.

If code or a search can answer the question, research it instead of listing an
Open Question. List it only when the answer needs the user's preference or a
fact only the user has.

**Choose a section for each unknown.** Use two factors: confidence in the answer
and the cost of being wrong:

- **Confident and low-impact** — A wrong guess causes contained rework inside
  one Design subsection. Add an `## Assumptions` line with `confidence: high`
  and continue. Do not spend a turn on it.
- **Everything else** — You are unsure, or the answer changes the plan split,
  acceptance criteria, an external contract, or the solution shape. Add an
  `## Open Questions` entry and ask it in one turn.

When the factors disagree, use impact. Ask about a high-impact item even when
you feel confident, because the cost of being wrong matters more than its odds.

**Use a prototype for questions that need something concrete.** Examples include
interaction feel, a state model that "feels right", and a layout tradeoff visible
only after building. Append `[needs prototype]`, invoke `varde-prototype` for
that question, and resume with its answer.

## Challenge the plan

Act as a sparring partner, not a passive interviewer. Use planning to resolve
*what* to build and its best shape, not *whether* to build it.

- **Give opinions, not just questions.** Say what is strong and why; call out
  what is weak, overcomplicated, or likely to cause trouble, part by part ("the X
  part is solid; I'd reconsider Y because Z") rather than one pass/fail verdict.
  Asked "is this a good idea?", answer directly before turning it back.
- **Propose better shapes** when you see one, and say why.
- **Keep the smallest reasonable version** that satisfies the concrete scenario.
  Use reuse, stdlib, native, existing-dependency, and one-line candidates as
  guiding principles, not automatic stop conditions.
- **Start with what, why, and fit.** Add specifics as the document firms up.
  Do not define signatures while the scope is still moving.

**Rare "nothing to build":** If the scenario is speculative or an existing
capability fully covers it, do not stop on your own. Ask: "This looks like [X]
already covers it — build anyway, or is this a non-issue?" Close as do-not-build
only after explicit agreement, then discard the plan directory created by
`references/plan-draft.md`.

## Terminology and standards

Add terminology and standards after the Problem/Solution seed makes the domain
concrete. Treat corrections as ordinary resolved items, not checkpoints.

Search for existing definitions and patterns using `references/plan-recipes.md`'s
"Find terminology definitions" and "Check for existing standards patterns"
commands. Show each match on one line. Ask whether each applies or is stale. If
there are no matches and the domain needs a definition or standard, write one
here or invoke `varde-knowledge` for a `definition`, `pattern`, or `decision`
note. Skip this when the domain language is already clear. Write each result
into `plan.md` as it settles, not in a batch.

## Per-turn steps

In each chat turn, ask the top open question, wait, write the answer, and ask
the next question. Keep the document open as a second channel. A user edit is
an answer and counts as the turn's answer. Do not leave work there for the user
to find.

**Watch the doc.** At the start of every turn, before responding, re-read
`plan.md` and diff it against your snapshot from the last turn. Any change to
`## Open Questions`, `## Assumptions`, `## Design`, `## Non-goals`, or
`## Constraints` you did not make is a user edit — treat it exactly like a chat
answer. Process doc edits and the chat message together, then run the continuous
check before responding.

**Resolve an item** through either channel: update the matching `## Design`
subsection (or `Non-goals`/`Constraints`) with the confirmed decision in the
structured form required by `assets/PLAN-TEMPLATE.md`; append
`<question> → <answer>` to `## Decisions so far`; remove the resolved line. Move
an explicitly accepted assumption into the decision log instead of leaving it
open. Then check whether the answer creates new unknowns and add each one.

Edit the file the moment each item resolves, one at a time.

**Ask one question per turn.** Use this rule for every item routed to
`## Open Questions`: items needing the user or expensive to get wrong. Take the
highest-value item, ask it in `references/plan-interview.md`'s inline
numbered-menu format with your recommendation, and wait.

Ask the question that unblocks the most first. A question that changes the
solution shape comes before one that chooses between two spellings.

Batch only during triage. Show confident, low-impact assumptions together at the
exit check; do not merge them back into a multi-question turn. Two questions in
one turn split the user's attention and usually produce a clean answer to only
one.

**Doc-driven mode is opt-in.** When the user asks to work in the document, for
example "just put them in the doc", "I'll edit it directly", or "stop asking",
switch modes. Leave entries in `## Open Questions` in live-question format for
the user to answer in place. Stop asking in chat until the user asks you to
resume. Say that you switched so the change of channel is explicit.

## Continuous check

Every turn, scan the document for implicit assumptions in Design or AC that are
not listed and add them with calibrated confidence. Recalibrate listed
assumptions when needed. Add unknowns exposed by the latest answer.

When a chunk of Design firms up or before the final completeness check, spawn a
subagent to check both sections for completeness. Give it the current `plan.md`
and confirmed scope. Tell it to find missed assumptions and flag miscalibrated
confidence. It returns
`{ item, kind: "missed_assumption"|"missed_question"|"miscalibrated", location,
note }`. Merge missed entries in. This is the same check run as a deeper sweep;
it does not replace the per-turn scan.

## Exit criteria

Before proposing the final completeness check, scan for gaps using
`references/plan-fundamentals.md`'s self-review checklist. Add each gap as a new
Open Questions entry and continue the loop.

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
