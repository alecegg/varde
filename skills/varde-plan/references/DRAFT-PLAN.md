# Draft Plan

## Create the draft

Before the first question, create the draft plan as a new file.

**Plan id.** Get the UTC date with `date -u +%Y-%m-%d` and form
`<YYYY-MM-DD>-<slug>-draft` so the directory sorts chronologically under
`memory-bank/working/plans/`. Use a temporary slug from the initial prompt —
confirmed and finalized during plan fundamentals. Collisions across sessions
started the same day on a similar prompt are the one realistic race: check
`ls memory-bank/working/plans/ | grep <candidate-id>` immediately before
creating the directory; if it exists, append `-2`, `-3`, etc. Keep `<plan-id>`
stable for the rest of the session.

Create the concept file at `memory-bank/working/plans/<plan-id>/plan.md` using
the frontmatter and body template in `assets/PLAN-TEMPLATE.md`, substituting
the initial prompt for the title.

## Seed the body

Seed immediately with a genuine first-pass understanding — not an empty
skeleton. From the initial prompt plus a quick repo read, write a best-guess
`## Problem` / `## Solution`, fill whatever `## Design` and `## Acceptance
criteria` are already settled, and route every remaining unknown
into `## Open Questions` or `## Assumptions` (formats in `GROW-DOC.md`). This
seed is the first turn of the growth loop, not a placeholder to fill later.

**Single writer per plan.** Once a session is actively planning `<plan-id>`,
it's the only writer until it commits or explicitly hands off (e.g. via
`RESUME-PLANNING.md`). Any scope-signal or research subagent is read-only
against `plan.md` — it returns findings for the orchestrating session to
write, never editing `plan.md` itself. Stage and commit only
this plan's own directory (see `PLAN-AUTHORING.md`'s Commit and prompt
section) so a concurrent session on a different plan is never touched.

## Editing as decisions land

After each planning phase, apply a targeted edit to overwrite the relevant
placeholder with the confirmed decision. Write it in the structured spec form
required by `assets/PLAN-TEMPLATE.md`'s writing-style rule (bullets,
`key: value`, signatures) — prose paragraphs are reserved for
`Problem`/`Solution` only, never for `Design`, `Decisions so far`,
`Open Questions`, or `Assumptions`. Re-read the file immediately before
editing to catch conflicting changes — especially once
`references/GROW-DOC.md` starts, since the user may edit `plan.md`
directly between turns.
`## Open Questions` and `## Assumptions` update throughout the session as
items resolve or new ones surface.

**Editing a section.** Anchor the edit on the existing placeholder or prior
text of the section — never on the section header alone. The header line
stays; only its body changes. Since a targeted edit requires an exact
`old_string` match, a stale anchor fails loudly instead of writing to the
wrong place.

**Running decision log.** After each user answer, append one line to
`## Decisions so far` before asking the next question: `<question> → <answer>`
(gist only, no reasoning paragraph). Edit immediately — do not batch.
