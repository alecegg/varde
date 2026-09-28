---
name: varde-review
description: "Review code or a running UI and act on findings: report without editing, fix a review or GitHub PR feedback and CI failures, run visual QA, simplify just-changed lines, or triage code-scan findings. Not for scan-rule authoring or agent documents like SKILL.md or AGENTS.md."
---

# Review and improve code

Reporting is the default. When the user explicitly asks to fix, write the report, then run `fix` on that review in the same session.

The harness invokes this workflow as a skill. `varde-review` is not a shell
executable. Check that the harness has this skill installed instead of using
`command -v varde-review` or reporting a missing CLI.

Before implementation edits, apply `references/review-gates.md`. Carry its
verdict through execution and completion, including changes made by this skill.

## Choose the mode

| The request is | Read |
|---|---|
| Review a diff, branch, or code area and write down what is wrong | `references/report.md` |
| Apply the findings an earlier review already wrote down | `references/fix.md` |
| Address review threads or failing checks on an open GitHub PR | `references/fix.md` (PR source routes to `references/fix-pr.md`) |
| Inspect a running web, iOS simulator, or macOS app visually and through its interactions | `references/visual.md` |
| Tidy up what was just changed — naming, redundancy, consistency — with no findings file | `references/simplify.md` |
| Run a `varde-code` scan and decide what its findings mean | `references/scan.md` |

## Gotchas

- `<working>` (local, uncommitted) and `<knowledge>` (committed): resolve once
  before first use with `varde-workflow paths --json`; use its absolute
  `data.working`/`data.knowledge` paths for this session and pass them to
  subagents. If the command fails, retry it once with escalated access; if it
  still fails, ask the user for the paths. Do not guess storage paths. A
  location outside the repo skips git ops (`check-ignore`, `mv`, `status`);
  use plain file ops.
