<!-- kind: reference -->
# Independent review gates

Load `varde-change`: use your skill tool, or read `../../varde-change/SKILL.md`;
route every implementation change (source, configuration, documentation,
fixes, refactors, prototypes in source) through it. Read-only investigation,
workflow bookkeeping, and prototype files under `<working>` need no gate.

## One review per change

- One independent review per plan or change, on the whole diff since a fixed
  `base` commit, on two axes: Spec (the plan, task, or linked specs) and
  Standards (every touched category in `varde-review`'s report-categories.md).
- Every text change (skill, agent document, doc) also gets the
  `varde-agent-doc-authoring` review; load `varde-agent-doc-authoring`: use your skill tool, or read `../../varde-agent-doc-authoring/SKILL.md`.
- For a skill or agent document, one clean-context reviewer covers both
  reviews together; do not run two reviewers.
- The reviewer never approves its own work; one fixer applies the findings.

## The report

One `review.md` holds the findings and a header naming:

- `verdict`: `approved` or `changes-requested`
- `reviewer`
- `base`: the fixed commit
- `head`: the reviewed commit

## Re-check a fix

- One fixes-only re-review answers a behaviour-changing fix;
  new findings block only at critical or high severity.
- Any other fix gets a header-only re-check: the reviewer confirms the diff
  since the old `head` holds only the named fixes, then rewrites `head`.
- Either way `head` covers every commit before conclusion.

## The only gate

`varde plan conclude <dir>` is the only gate: it exits 0 only when the merged
commit equals `head` and the verdict is `approved`, and otherwise names the
verdict or both commits.
