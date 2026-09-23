# Triage pass

Read one review folder per pass.

## Preconditions

Before processing findings:

1. Confirm `review.md` and generated nav-only `index.md` exist.
2. Load the category order from the generated `index.md`.
3. Confirm that each active category completed or was intentionally skipped.
4. Validate every finding's required fields.
5. Confirm deferred findings use `Disposition: blank`.

If a finding is malformed, stop the pass. Report its category and identifier.

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

Process categories in the order from the generated `index.md`. Process findings
in file order. Run the automated pass before the human pass. Skip findings with
nonblank dispositions.

In build mode, as described in `references/fix.md`, the automated pass attempts
every finding and uses the escalation check. Only findings that trip the gate,
shown by an `Escalated:` note, reach the human pass. The pass already applied
and verified every other finding.

## Human interaction

Show one finding at a time. Include its severity, location, summary, and all
solutions. If an `Escalated:` note is present, show it first. It explains why
this finding needed a human in build mode. Wait for a clear choice before
showing the next finding.

- `fix` applies the selected solution and verifies it.
- `dismiss` records the user's reason.
- `action-item` creates or updates the companion plan.
- `discuss` leaves the finding open.

After listing the options, state your recommendation and one-sentence reason.
Base the recommendation on:

- **Severity:** prefer `fix` for high-severity findings over deferral
- **Solution confidence:** prefer `fix` when confidence is high and the change
  is contained. Prefer `action-item` when the fix is large or affects a hot path
- **Blast radius:** a fix limited to one call site is safer than a change
  across packages
- **Blocking:** discuss a finding that blocks the build before dismissing it

## Completion

Use `references/fix-companion-plan.md` to create companion plans for action-item
findings. Then use `references/fix-closing-summary.md` to rescan dispositions,
update status, and archive the review.
