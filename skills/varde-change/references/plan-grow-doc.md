# The growth loop

`references/plan-start.md` seeds `plan.md` on the first turn; run this loop
every later turn to sharpen it.

Each later turn: research what the repo can answer (`references/varde-code.md`)
and run plan-fundamentals' external interface check when consumers are
touched.

## Routing unknowns

Route every unknown instead of blocking. Code or search can answer it →
research, don't list it. Confident **and** a wrong guess stays inside one
Design subsection → `## Assumptions` with `confidence: high`; don't spend a
turn. Everything else — unsure, or touching the plan split, AC, an external
contract, or solution shape → `## Open Questions` with a recommendation, and
ask. Impact beats confidence.

A question that needs something concrete — an open UI shape, interaction feel,
a state model, a layout tradeoff visible only once built — gets
`[needs prototype]`; invoke `varde-prototype` for it and resume with its
answer. Do not raise prototyping when the UI shape is already settled.

**Push back.** Challenge the idea directly; propose a better shape when you
see one, preferring the smallest version. If the scenario is speculative or
an existing capability seems to cover it, offer do-not-build — "This looks
like [X] already covers it — build anyway, or is this a non-issue?" — and
close as do-not-build only on explicit agreement, then discard the plan
directory.

## Design It Twice

For a genuinely open interface decision (no existing pattern): state
constraints (`type_hierarchy` when extending a type); sketch a minimal and a
caller-convenient alternative, each with a usage example and trade-off;
recommend one or a hybrid; log why the other lost in `## Decisions so far`.

## Terminology and standards

Once the seed makes the domain concrete, search `<knowledge>/` for specs,
decisions, definitions, and patterns on the feature. Link the ones that apply
under `## Related`; put any that look stale into `## Open Questions` as one
item. Record a missing definition with `varde-knowledge`. When
`<knowledge>/specs/<domain>.md` covers code this plan changes, add the domain
to `observed_specs`.

## Per-turn steps

**Watch the doc.** At the start of every turn, re-read `plan.md` and diff it
against your last snapshot. Any change to `## Open Questions`,
`## Assumptions`, `## Design`, `## Non-goals`, or `## Constraints` you did not
make is a user edit and counts as an answer. Process doc edits and the chat
message together.

**Resolve an item:** write the decision into its
`## Design` subsection (or Non-goals/Constraints) in the template's form, append
`<question> → <answer>` to `## Decisions so far`, remove the resolved line, and
add any unknowns the answer exposes. An accepted assumption moves to the
decision log too.

**Single writer.** Only this session edits `plan.md`; pass resolved absolute
`<working>` and `<knowledge>` paths to research subagents so they do not
re-resolve storage. Research subagents return
findings.

**Ask** the highest-value Open Question per `references/interview.md`,
solution-shape questions before spelling ones.

**Doc-driven mode is opt-in.** When the user asks to work in the document
("just put them in the doc", "stop asking"), say you are switching, leave Open
Questions in place for the user to answer there, and stop asking in chat until
the user asks you to resume.

## Exit criteria

Each turn, list implicit assumptions in Design/AC and run
`references/plan-fundamentals.md`'s self-review. Finalize when
`## Open Questions` has no live item (only `n/a — reason`) and self-review
finds nothing new.
