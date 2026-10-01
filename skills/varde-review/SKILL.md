---
name: varde-review
description: "Review code or a running UI and act on findings: report without editing, fix a review or GitHub PR feedback and CI failures, run visual QA, simplify just-changed lines, or triage code-scan findings. Not for scan-rule authoring or agent documents like SKILL.md or AGENTS.md."
---

# Review and improve code

Reporting is the default; when a new review also asks for fixes, write the
report, then run `fix` on that review in the same session.

Before implementation edits, apply `references/review-gates.md` unless a
caller's approved gate already covers them.

## Choose the mode

| The request is | Read |
|---|---|
| Review a diff, branch, or code area and write down what is wrong | `references/report.md` |
| Fix one named, already recorded standalone finding | `## One recorded finding` below |
| Apply the findings an earlier review already wrote down | `references/fix.md` |
| Address review threads or failing checks on an open GitHub PR | `references/fix.md` (PR source routes to `references/fix-pr.md`) |
| Inspect a running web, iOS simulator, or macOS app visually and through its interactions | `references/visual.md` |
| Tidy up what was just changed — naming, redundancy, consistency — with no findings file | `references/simplify.md` |
| Run a `varde-code` scan and decide what its findings mean | `references/scan.md` |

## One recorded finding

Confirm in its category file:

- its ID and current location;
- one concrete solution;
- decision evidence: the user's named request for a one-solution `auto-fix`
  finding, or approval of that solution for a `triage` finding.

Then, in the same turn, run `varde-change` build and follow its micro-change
section `One standalone review finding`. Create no report, automated pass,
task, or companion plan, and leave other findings untouched.
Missing any item, or a plan-owned finding: use `references/fix.md`.

## Gotchas

- `varde-review` is a skill invoked by the harness, not a shell executable; do not check it with `command -v` or report a missing CLI.
- Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
- At the end of a write flow, record real obstacles through `varde-learn` and durable decisions through `varde-knowledge`; otherwise skip.
