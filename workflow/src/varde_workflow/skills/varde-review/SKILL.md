---
name: varde-review
description: "Use this skill when you need to review code and act on the findings: report on a diff, branch, or code area without editing, check a plan against its tasks and criteria, fix the findings of an earlier review, address review threads and failing checks on a GitHub PR, fix one named recorded finding, simplify just-changed lines, or decide what a code scan's findings mean."
recommends: [varde-build, varde-code, varde-knowledge, varde-learn, varde-scan]
---

# Review and improve code

Reporting is the default. When a new review also asks for fixes, write the
report, then apply its findings in the same session (the fix row below).

## Choose the mode

| The request is | Read |
|---|---|
| Check a plan against its tasks and criteria | `references/conform.md` |
| Review a diff, branch, or code area and write down what is wrong | `references/report.md` |
| Fix one named, already recorded standalone finding | `## One recorded finding` below |
| Apply the findings an earlier review already wrote down | `references/fix.md` |
| Address review threads or failing checks on an open GitHub PR | `references/fix.md` (`## PR source`) |
| Tidy up a just-committed change — naming, redundancy, consistency — with no findings file | `references/simplify.md` |
| Decide what a code scan's findings mean | — |

## One recorded finding

Confirm in its `review.md`:

- its ID and current location;
- one concrete solution;
- decision evidence: the user's request names the finding; an intended-behaviour
  change needs approval.

Then fix that finding in one bounded change in the same turn. Create no report,
automated pass, task, or companion plan, and leave other findings untouched.
Missing any item, or a plan-owned finding: use `references/fix.md`.
