---
type: reference
description: Defines Varde's versioned workflow artifact mechanics.
generated: { by: codex/gpt-5, at: 2026-09-19T02:30:00Z }
paths:
  - clis/workflow/varde-workflow/src/artifact.rs
  - clis/workflow/varde-workflow/src/workflow_schema.rs
  - clis/workflow/varde-workflow/src/conclusion.rs
---

# Workflow artifact kernel

`varde-workflow` owns mechanical workflow artifact operations.
Skills retain policy judgment and qualitative decisions.

## Envelope

Schema version `1` requires artifact type, identifier, relationships,
and provenance. Status remains optional across artifact types.
The content revision derives from exact source bytes.

Legacy Markdown receives a deterministic read-only envelope.
Its derived identifier uses the source content revision.
Legacy inspection never changes the underlying source bytes.

## Direct edits

Direct Markdown editing remains supported for versioned artifacts.
Valid edits produce a new revision during inspection.
Invalid edits return field diagnostics and preserve bytes.
No command repairs malformed content silently.

## Output and availability

Machine output uses one versioned JSON response envelope.
Success payloads appear under `data`. Failures use `error`.
Human output remains separate from machine-readable output.

Mutations require the CLI and stop when unavailable.
Read-only workflows may use an explicitly degraded fallback.

## Validation and ownership

`varde plan validate` checks statuses, frontmatter keys, plan-only fields, and
task ownership (`modifies`/`creates`/both rename endpoints), flagging stray
paths against the plan's `shared:` list and each task's `owns`. `execution-wave`
conflicts tasks by glob intersection of their `owns` patterns.

## The review report

One `review.md` per plan or change holds the verdict and the reviewed commits:

- `verdict`: `approved` or `changes-requested`
- `reviewer`
- `base`: the fixed commit
- `head`: the reviewed commit

`varde plan conclude` is the only gate and accepts only an approved verdict
whose `head` equals the merged commit (see
[workflow-conclusion](workflow-conclusion.md)).
A fixes-only re-review or header-only re-check rewrites `head`.

## Explicit integration authority

Each parallel task gets one worktree and branch
(`scripts/worktree-wave.sh start`). `integrate` audits every task commit with
`check-task-ownership`, runs one combined check, bisects failures to the
culprit task, and fast-forwards the plan branch. `release` removes the task and
integration worktrees. Workers never merge or mutate plan state; the plan
branch's owner holds both.