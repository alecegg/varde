---
name: varde-review
description: "Review code and act on findings: report findings without touching source, apply an existing review's findings, simplify just-changed lines, or run a varde-code scan to triage findings and author rules. Not for planning, building new functionality, or docs."
---

# Review and improve code

Reporting is the default. Changing source requires an explicit request.

## Choose the mode

| The request is | Read |
|---|---|
| Review a diff, branch, or code area and write down what is wrong | `references/report.md` |
| Apply the findings an earlier review already wrote down | `references/fix.md` |
| Tidy up what was just changed — naming, redundancy, consistency — with no findings file | `references/simplify.md` |
| Run a `varde-code` scan and decide what its findings mean, or add and tune scan rules | `references/scan.md` |

Load only the reference the request needs.
Then load its explicitly required supporting files.

## Gotchas

- Paths written `<working>/…` and `<knowledge>/…` resolve per
  `references/memory-locations.md`. Read it before the first memory read or write.
- Report mode never changes source files.
- Mutation requires fix or simplify mode.
- When authoring rules, confirm thresholds with the user.
- Every reported scan finding gets an explicit verdict.
- Load `references/worktree.md` before isolated fixes.
