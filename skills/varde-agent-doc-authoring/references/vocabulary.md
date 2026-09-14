# Vocabulary for skill quality

Leading words and failure modes worth thinking in while writing or reviewing a skill. Load this when drafting a new skill's structure, tuning invocation mode, or diagnosing why a skill misbehaves.

## Predictability is the root virtue

A skill exists to wrangle determinism out of a stochastic system. The goal is the agent taking the same *process* every run — not the same output (a brainstorming skill should predictably diverge). Every lever below serves this.

## Context pointers

A **context pointer** is any reference held in the agent's context that names some out-of-context material and encodes the condition for reaching it: a skill's `description`, a line in `AGENTS.md` naming a doc, a "see also" inside a reference file. The pointer's *wording* — not its target — decides whether and how reliably the agent reaches the material. A must-have target behind a weakly worded pointer is a variance bug; fix the wording before inlining the material as a workaround.

A pointer does two jobs: state what the material is, and name the **branches** — the distinct cases — that should send the agent there. Every word of an always-loaded pointer (an `AGENTS.md` line, a skill description) is paid on every turn whether or not it fires, so prune it harder than the body it points to:

- Front-load the leading word — the word the user or the situation actually says — since that's where the pointer does its triggering work.
- One trigger per branch. Synonyms restating one branch are duplication, not extra coverage.
- Cut identity the body already states; a pointer names *when*, not *what it is in detail*.

## Information hierarchy

Content in any agent document is either a **step** (an ordered action the agent performs) or **reference** (a definition, rule, or fact consulted on demand) — most documents mix both. Rank each piece on a ladder by how immediately it's needed:

1. **In-file step** — the primary tier: what the agent does, in order.
2. **In-file reference** — consulted on demand but cheap enough to keep inline. A flat peer-set (every rule in a checklist at the same rung) is a legitimate shape here, not a smell.
3. **Disclosed reference** — pushed to a separate file behind a context pointer, loaded only when the pointer fires.

Push too little down and the top bloats past relevance; push too much down and the agent silently skips material it actually needed inline. **Branching is the test**: inline whatever every branch needs, disclose whatever only some branches reach. In a document with ordered steps, in-file reference that should have been disclosed sits between the steps and turns attending to it into a coin-flip — this is a correctness risk on top of the token cost.

## Co-location

Where the information hierarchy decides *how far down* a piece of content sits, co-location decides *what sits beside it* once it's there: keep a concept's definition, rules, and caveats under one heading instead of scattering them across the document. The test is whether the document reads like it was written for the agent to consult in one pass — grouped material does, scattered material doesn't. Distinct from duplication (the same meaning stated twice); co-location is about one meaning's parts staying adjacent, not about a meaning repeating.

## Invocation: two loads

- **Model-invoked** (default: `description` present, no `disable-model-invocation`): the agent can fire it on its own, and other skills can reach it. Costs **context load** — the description sits in every context window whether or not the skill fires this turn.
- **User-invoked** (`disable-model-invocation: true`): invisible to the agent; only a human typing the name reaches it, and no other skill can invoke it. Zero context load, but costs **cognitive load** — the human becomes the index that must remember the skill exists.

Pick model-invocation only when the agent must reach the skill unprompted, or another skill needs to invoke it. If it only ever fires by hand, make it user-invoked and skip the context cost.

When user-invoked skills multiply past what's memorable, add a **router skill**: one user-invoked skill that just lists the others and when to reach for each.

## Leading words

A leading word is a compact concept already living in the model's pretraining that the agent thinks with while running the skill — *lesson*, *fog of war*, *tracer bullets*, *tight loop*. Repeated as a token (not restated as a sentence) it accumulates a distributed definition and anchors a whole region of behavior in very few tokens, by recruiting priors the model already holds.

It pays off twice: in the body it anchors *execution* (the agent reaches for the same behavior every time the word appears); in the `description` it anchors *invocation* (when the same word appears in the user's prompts, docs, and code, the agent links that language to the skill and fires it more reliably).

When drafting or reviewing, look for a triad spelled out in full three times, or a description spending a sentence to gesture at one idea — each is a candidate to collapse into one pretrained word. Prefer an existing word with strong priors over coining a new one (a made-up term has to be defined from scratch, at token cost).

## Failure modes to diagnose against

- **Premature completion** — a step ends before it's genuinely done because attention slipped to *being done*. A completion criterion has two independent levers: **clarity** (can the agent tell done from not-done? a vague bound like "understanding reached" invites the rush) and **demand** (how much the criterion actually requires — "every modified caller accounted for" forces more legwork than "list the changes"). Fix clarity first — sharpen the bound, cheap and local. Demand isn't step-bound either: "every rule applied" binds a flat reference document exactly the way "every step done" binds a sequence. Only split the sequence to hide later steps if the criterion is irreducibly fuzzy and you've actually observed the rush — hiding later steps only clears attention across a real context boundary (a hand-off, a subagent dispatch), never within one inline call.
- **Duplication** — the same meaning stated in more than one place. Costs maintenance and tokens, and inflates that meaning's prominence past its real rank. Keep one authoritative location per meaning (single source of truth).
- **Sediment** — stale content that accumulated because adding felt safe and removing felt risky. The default fate of any skill without active pruning; check every line for continued relevance.
- **Sprawl** — the skill is simply too long, even if every line is live and unique. Cure is progressive disclosure: push reference behind pointers in `references/`, and split by branch or sequence so each path loads only what it needs.
- **No-op** — an instruction the model already follows by default, so it costs load to say nothing. Test: does this line change behavior versus what the agent would do anyway? A weak leading word (*be thorough* when the agent is already thorough-ish) is a no-op; the fix is a stronger word (*relentless*), not more prose.
- **Negation** — steering by prohibition backfires: naming the forbidden behavior makes it more available in context, not less ("don't think of an elephant"). Prompt the positive — state the target behavior so the banned one is never spoken. Keep a "don't" only as a hard guardrail that has no positive phrasing, and even then pair it with what to do instead.

## When to split one document into two

Splitting spends one of the two loads above (a new pointer, a new file to keep relevant), so split only when the cut earns it. The reliable case is **by sequence**: cut a run of steps where the steps still ahead tempt the agent to rush the one in front of it — hiding them behind a hand-off or subagent boundary drives more legwork on the current step. The reverse mistake is just as real: merging two sequences that were split for this reason re-exposes each step to what follows and reintroduces premature completion. Splitting by invocation (should this fire on its own, or only as part of a larger flow) is the other common case; judge it the same way as any other model-invoked vs. disclosed-reference choice.

## Pruning discipline

Keep each meaning in exactly one place. When reviewing, check every remaining line for **relevance** (does it still bear on what the skill does?), then hunt no-ops sentence by sentence — run the no-op test in isolation, and when a sentence fails it, delete the whole sentence rather than trim words from it. Be aggressive; most prose that fails the test should go, not be softened.
