---
name: varde-review
description: "Review code or a running UI and act on findings: report without editing, fix a review or GitHub PR feedback and CI failures, run visual QA, or simplify just-changed lines. Use varde-scan for code-scan findings. Not for scan-rule authoring, agent documents like SKILL.md or AGENTS.md, or fixing a bug no review or PR recorded (varde-change)."
recommends: [varde-change, varde-code, varde-knowledge, varde-learn, varde-scan]
---

# Review and improve code

Reporting is the default; when a new review also asks for fixes, write the
report, then apply that review's findings in the same session (the "Apply the findings" row below).

A review is one `review.md` whose header holds `verdict`, `reviewer`, `base`,
and `head` (`references/report-format.md`); `varde plan conclude` is the only
gate.

## Choose the mode

| The request is | Read |
|---|---|
| Review a diff, branch, or code area and write down what is wrong | `references/report.md` |
| Fix one named, already recorded standalone finding | `## One recorded finding` below |
| Apply the findings an earlier review already wrote down | `references/fix.md` |
| Address review threads or failing checks on an open GitHub PR | `references/fix.md` (`## PR source`) |
| Inspect a running web, iOS simulator, or macOS app visually and through its interactions | `references/visual.md` |
| Tidy up a just-committed change — naming, redundancy, consistency — with no findings file | `references/simplify.md` |
| Run a `varde` scan and decide what its findings mean | Load `varde-scan`: use your skill tool, or read `../varde-scan/SKILL.md`; delegate scanning, triage, and persistence to it and consume its `<working>/scan/findings.md` pipe-separated findings format. |

## One recorded finding

Confirm in its `review.md`:

- its ID and current location;
- one concrete solution;
- decision evidence: the user's request names the finding; an intended-behaviour
  change needs approval.

Then, in the same turn, load `varde-change`: use your skill tool, or read
`../varde-change/SKILL.md`, run build, and follow its micro-change section
`One standalone review finding`. Create no report, automated pass, task, or
companion plan, and leave other findings untouched.
Missing any item, or a plan-owned finding: use `references/fix.md`.

## Gotchas

- `varde-review` is a skill invoked by the harness, not a shell executable; do not check it with `command -v` or report a missing CLI.
- Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
- Use the role registered for the active harness when dispatching a reviewer or builder. Verify full documented `varde` argv against current help, and search split-string callers as well as literal command text.
- At the end of a write flow, load `varde-learn`: use your skill tool, or read `../varde-learn/SKILL.md`, and record real obstacles with it; load `varde-knowledge`: use your skill tool, or read `../varde-knowledge/SKILL.md`, and record durable decisions with it; otherwise skip.
