# Draft Plan

## Create the draft

Create the draft plan as a new file before asking the first question.

**Plan id:** Get the UTC date with `date -u +%Y-%m-%d` and form
`<YYYY-MM-DD>-<slug>-draft` so the directory sorts chronologically under
`<working>/plans/`. Use a temporary slug from the initial prompt —
confirmed and finalized during plan fundamentals. Collisions across sessions
started the same day on a similar prompt are the one realistic race: check
`ls <working>/plans/ | grep <candidate-id>` immediately before
creating the directory; if it exists, append `-2`, `-3`, etc. Keep `<plan-id>`
stable for the rest of the session.

Create `<working>/plans/<plan-id>/plan.md` with the frontmatter and
body template from `assets/PLAN-TEMPLATE.md`. Use the initial prompt as the
title.

## Seed the body

Seed the file immediately with a genuine first-pass understanding, not an empty
skeleton. Read the initial prompt and repository briefly. Write a best-guess
`## Problem` / `## Solution`, fill any settled `## Design` and `## Acceptance
criteria`, and route every remaining unknown into `## Open Questions` or
`## Assumptions`. Format open questions as
`- **<question>** — <importance>. Recommendation: <answer> — <reason>.`
Format assumptions as `<assumption> — affects: <area> — confidence:
<low|medium|high>`. This seed is substantive, not a placeholder.

**Single writer per plan:** Once a session is actively planning `<plan-id>`,
it's the only writer until it finalizes or explicitly hands off (e.g. via
`references/plan-resume.md`). Any scope-indicator or research subagent is read-only
against `plan.md` — it returns findings for the orchestrating session to
write, never editing `plan.md` itself. If the plan path is tracked, stage and
commit only this plan's directory. If it is ignored, keep the directory local.

## Editing as decisions land

After each planning phase, apply a targeted edit that replaces the relevant
placeholder with the confirmed decision. Use the structured spec form
required by `assets/PLAN-TEMPLATE.md`'s writing-style rule (bullets,
`key: value`, signatures) — prose paragraphs are reserved for
`Problem`/`Solution` only, never for `Design`, `Decisions so far`,
`Open Questions`, or `Assumptions`. Re-read the file immediately before
editing to catch conflicting changes — especially once
`references/plan-grow-doc.md` starts, since the user may edit `plan.md`
directly between turns.
Update `## Open Questions` and `## Assumptions` throughout the session as items
resolve or new ones appear.

**Editing a section:** Anchor the edit on the existing placeholder or prior
body text, leaving the header line untouched. Since a targeted edit requires an exact
`old_string` match, a stale anchor fails loudly instead of writing to the
wrong place.

**Running decision log:** After each user answer, append one line to
`## Decisions so far` before asking the next question: `<question> → <answer>`.
Write only the gist, not a reasoning paragraph, when the answer lands.
