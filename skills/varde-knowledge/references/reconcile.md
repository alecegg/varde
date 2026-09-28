# Reconcile knowledge notes against code

Knowledge notes can drift from the code they describe. Reconciliation follows
these shared rules:

- **Evidence or no edit.** Point at the code that no longer matches — a
  changed signature, a removed flag, a moved path, a fix that landed. No
  evidence, no edit.
- **Confirm first.** Propose the correction or status change with its
  evidence and wait for the user to confirm.
- **Never delete.** Correct a stale note in place.

## Notes

Read the note, then the code in its `paths` or links, and compare by hand. A
`reconciled.sha` far behind `HEAD` is a drift signal. After confirming or
correcting, stamp `reconciled: { at: <ISO 8601>, sha: <HEAD sha> }`.

## Friction

Friction-item lifecycle belongs to the `varde-learn` skill. Use that skill for
friction reconciliation; this Knowledge workflow changes notes only.
