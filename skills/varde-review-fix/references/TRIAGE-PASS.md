# Triage pass

The triage pass reads one review folder. It never searches across reviews.

## Preconditions

Before processing findings:

1. Confirm `review.md` and generated nav-only `index.md` exist.
2. Load the category order from the generated `index.md`.
3. Confirm each active category completed or was intentionally skipped.
4. Validate every finding's required fields.
5. Confirm deferred findings use `Disposition: blank`.

Malformed findings stop the pass. Report the category and identifier.

## Parsing

Findings begin at level-two headings. Read through the next level-two heading.
Use these exact bold fields:

- `Severity`
- `Label`
- `Disposition`
- `Location`

Read `### Summary` and `### Solutions` as structured sections. Labels are
`auto-fix` and `triage`. Dispositions are `blank`, `fix`, `dismiss`, and
`action-item`.

## Order

Process categories in the order from the generated `index.md`. Process findings in file
order. Run the automated pass before the human pass. Skip any finding with a
nonblank disposition.

In `mode=build` (see `SKILL.md` Mode resolution), the automated pass attempts
every finding, gated by the escalation check. Only findings that trip the gate
— an `Escalated:` note is present — reach the human pass. Everything else was
already applied and verified.

## Human interaction

Show one finding at a time. Include severity, location, summary, and all
solutions. If an `Escalated:` note is present, lead with it — it is why this
finding, unlike most in a build-mode pass, needed a human. Do not present the
next finding until the current choice is clear.

- `fix` applies the selected solution and verifies it.
- `dismiss` records the user's reason.
- `action-item` creates or updates the companion plan.
- `discuss` leaves the finding open.

After listing the options, state your recommendation and a one-sentence reason.
Base it on:

- **Severity** — high-severity findings generally warrant `fix` over deferral
- **Solution confidence** — prefer `fix` when confidence is high and the change
  is contained; prefer `action-item` when the fix is large or touches a hot path
- **Blast radius** — a fix confined to one call site is safer to apply now than
  one that fans across packages
- **Blocking** — findings that block the build should not be dismissed without
  discussion

## Completion

Follow `references/COMPANION-PLAN.md` to emit companion plans for action-item
findings, then `references/CLOSING-SUMMARY.md` for the disposition re-scan,
status update, and archive step.
