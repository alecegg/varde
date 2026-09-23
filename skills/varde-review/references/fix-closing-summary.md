# Closing summary

Use separate counts for automated fixes and triage:

```text
Review fix summary

Automated:
  fixed: <n>
  skipped: <n>
  reverted: <n>

Triage:
  fixed: <n>
  dismissed: <n>
  action items: <n>
  open: <n>
```

After the pass completes, update `triage_status` in the review's `review.md`.
Leave it `in-progress` when the human stops early.

Before closing, read every category file listed in `index.md`.
Check every `**Disposition:**` field. If any field is blank, leave the review
folder in place and keep its status `in-progress`. If no field is blank, set
`triage_status: complete`. Keep a nested review inside its parent plan bundle.
For a standalone review, move the folder to
`reviews/archive/<folder-name>` with `mv`, or `git mv` when tracked. Then set
`status: archived` in the moved `review.md`. Nested review completion does not
wait for companion plan tasks.
