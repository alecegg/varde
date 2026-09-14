# Closing summary

Report separate counts:

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

Update `triage_status` in the review's `review.md` when the pass completes. Leave it
`in-progress` when the human stops early.

Re-scan every category file listed in the generated `index.md` before closing.
Check every `**Disposition:**` field. If any field is blank, leave the review
folder in place and keep its status `in-progress`. If none are blank, set
`triage_status: complete`. For a nested review, leave the folder inside its
parent plan bundle. For a standalone review, move the folder to
`reviews/archive/<folder-name>` with `mv`, or `git mv` when tracked, then set
`status: archived` in the moved `review.md`. Nested review completion does not
wait for companion plan tasks.
