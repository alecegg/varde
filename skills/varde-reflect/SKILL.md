---
name: varde-reflect
description: >
  TRIGGER: At the end of a meaningful chunk of real work or investigation —
  or the moment friction, a durable lesson, or a session boundary appears —
  consolidate what the work produced into the right durable store. Works in
  any workflow, with or without other skills.
  SKIP: Skip for trivial turns that produced no reusable friction, no durable
  fact, and no context worth carrying to a later session.
  Example phrases: "wrap up this session", "reflect on this work", "capture
  what we learned before I stop".
---

## Instructions

Reflect on the work just done and route anything worth keeping to the store that owns it. This is a **thin triage skill**: every top-level workflow invokes it at close, but it writes nothing unless the completed work meets a sink's value threshold. It decides which sinks (and the reconcile motion) apply and delegates each write to its owning leaf. It never writes friction items, knowledge notes, or handoff docs itself.

Reflection runs two directions. The three **sinks** below carry fresh work *into* the stores (capture). A fourth motion, **reconcile**, runs the reverse — retiring stored items the work just made stale — and is likewise delegated to the leaf, never written here (see "Reconcile" below).

Nothing here is gated on skill use. An agent doing raw exploration in any repo — no other varde skill involved — should reach for this the moment the work is worth consolidating. Each leaf (`varde-friction`, `varde-knowledge`, `varde-handoff`) is also independently invocable; this skill is an affordance that fans out to the right ones, not a gate in front of them.

## The three sinks

| Sink | Route to | Fires when the moment is… |
|---|---|---|
| **Friction** | `varde-friction` | a concrete obstacle, workaround, missing/stale guidance, or a positive technique worth generalizing occurred in the work — in *any* workflow, not just skill mechanics |
| **Knowledge** | `varde-knowledge` | the work produced a *durable* decision, finding, pattern, or definition a future session or another engineer would need |
| **Handoff** | `varde-handoff` | a **session boundary** — work is pausing or stopping, or a long run just completed and the next session should start cheaply from carried context |

## Entry point dispatch

| Invocation | Sinks considered |
|---|---|
| Bare `varde-reflect` (agent or user, at a stopping point) | all three; handoff only if this is a session boundary (see below); reconcile if code changed |
| `source=<skill>` (a skill's closing-step call, mid-session) | friction (scoped to that skill's own run) + knowledge; reconcile if that skill changed code; **no** handoff — the session continues |
| `boundary` (explicit "wrap up", or a top-level `varde-build` / `varde-orchestrate` completion) | all three; handoff always considered; reconcile if code changed |

**Outermost boundary only.** Handoff fires at the outermost stopping point, not a nested one — a child build completing inside an orchestrate run is not a boundary because more work is queued. When invoked from a nested completion, use `source=` (skip handoff); reuse the caller's existing "am I nested?" detection.

## Workflow

Assess the work just done, then run the applicable steps **in this order** — friction and knowledge capture first, then reconcile, handoff last — so reconcile has retired stale items before the handoff snapshots state, and the handoff can link to any note the knowledge step just wrote instead of restating it.

1. **Friction.** If the work contains concrete friction (obstacle, workaround, repeated manual step, missing/stale/misleading guidance, or a positive technique worth keeping), invoke `varde-friction`. For a `source=<skill>` call, scope capture to that skill's own execution and pass it as the `source`; otherwise review the current work retroactively. If nothing concrete occurred, skip — do not manufacture an item.

2. **Knowledge harvest.** If the work produced a *durable* fact — an architecturally-significant decision (and the alternatives it beat), a research finding, a reusable pattern, or a new domain term — invoke `varde-knowledge` to write the matching note (`decision` / `findings` / `pattern` / `definition`). Keep a **high bar**: skip anything session-local, obvious, already in code/plans/commits, or that a future session could re-derive cheaply. Prefer editing an existing note over creating a near-duplicate. Note the path of any note written — the handoff step links to it.

3. **Reconcile.** Only when this work **changed code** that could have resolved already-stored items (skip for pure exploration — nothing was fixed). Delegate the reverse motion to the leaf that owns each store: `varde-friction mode=reconcile` to retire open friction items whose obstacle the change fixed, and `varde-knowledge`'s "Reconciling knowledge against code" to correct notes the change drifted. Both are evidence-gated and confirm-gated in the leaf — reflect only triggers the pass and scopes it to what the work touched; it does not decide or write any transition itself. When friction flags an item for **promotion** (a durable lesson worth keeping past its fix), reflect coordinates the whole move — invoke `varde-knowledge` to write the note first, then let `varde-friction` archive the item — so the lesson is never dropped mid-transfer. Run this before handoff so the handoff reflects the retired/corrected state.

4. **Handoff.** Only at a session boundary (per the dispatch table). Invoke `varde-handoff` to write a carry-forward doc. Handoff is **not** gated on unfinished work — a completed long run still leaves decisions, pointers, and a git anchor worth carrying so the next session starts cheap rather than reloading the transcript. Pass links to any knowledge note the harvest step wrote as `kind: knowledge` links so the handoff references them instead of duplicating them.

5. **Report.** State concisely what each sink did — items captured, notes written (with paths), items reconciled (retired/corrected), handoff id/path — or that a step had nothing and was skipped. Never claim a write a leaf skill didn't make.

## Gotchas

- Every top-level workflow invokes this assessment at close. Leaf and helper
  skills do not, preventing duplicate capture and recursive routing. A no-write
  result is normal and should be reported briefly, not treated as a failed
  reflection.
- Stay thin. If you find yourself composing a friction item's fields or a knowledge note's body here, stop and delegate — the leaf owns the format and the write.
- Order matters: harvest knowledge before writing the handoff, so the handoff links to the note rather than embedding a copy that goes stale.
- A missing leaf skill (not installed in this repo) is not a hard error: note the sink was skipped for that reason and continue with the others.
- Don't double-capture. If a leaf was already invoked directly earlier this session for the same observation, don't re-route it here.
- The stores this routes into **persist and survive uninstalling the skills** — friction/project knowledge in-repo, user knowledge cross-project — and may quote source and paths. Reconcile is how items eventually leave; that's why it's a first-class motion here, not an afterthought. Each leaf documents its own storage and retention.
