# Reconcile knowledge notes against code

Knowledge notes can drift from the code they describe. Reconciliation follows
these shared rules:

- **Evidence or no edit.** Point at the code that no longer matches — a
  changed signature, a removed flag, a moved path, a fix that landed. No
  evidence, no edit.
- **Use existing authorization.** When the user explicitly asks to reconcile
  or update a note, apply an evidence-supported, unambiguous correction.
  Ask before an ambiguous or destructive change, or when no current evidence
  supports the proposed correction.
- **Never delete.** Correct a stale note in place.

## Notes

Read the note, then the code in its `paths` or links, and compare by hand. A
`reconciled.sha` far behind `HEAD` is a drift signal. After checking or
correcting, stamp `reconciled: { at: <ISO 8601>, sha: <HEAD sha> }`.

## Friction

Friction-item lifecycle belongs to the `varde-learn` skill. Use that skill for
friction reconciliation; this Knowledge workflow changes notes only.
