# Execution Reference

## Review checks

These checks are your whole review gate; skip `references/review-gates.md`.
The parent passes the plan subject id and resolved memory paths. Tasks inherit
that subject and its approved verdict; never initialize or record approval
yourself.

1. Before the first edit, run:

   ```sh
   varde-workflow review check --subject <subject-id> --checkpoint start --json
   ```

2. Before continuing interrupted work, run it with `--checkpoint resume`.
3. On exit 3 (OCC conflict), rerun the check. On exit 4 (a typed blocker),
   stop and return it to the caller.
4. Material drift from the approved scope or verification returns to the
   caller for a fresh verdict.

A verified task may be `done` with the aggregate implementation review
pending; the plan stays incomplete.

## Separate execution checkout

When the execution checkout differs from the approval checkout, load
`references/build-worktree.md` and add the caller-supplied binding to start/resume
checks: `--repository <approval-checkout>`, `--worktree
<absolute-worker-path>`, and `--binding <task-binding-id>` together. Stop if
that context is missing or rejected.

## Task kind and posture

| Task | Before the first edit |
|---|---|
| `kind: research` | Write the `creates` doc from primary sources outside the repo, citing each claim (URL, spec section, file:line); a decision ends with one recommendation. Then run Completion. |
| `debug` posture | Load `references/build-posture-debug.md`; keep `debug_evidence` per its Evidence contract. |
| `refactor` posture | Load `references/build-posture-refactor.md`. |
| `spike` posture | Plan to revert your own edits; skip the Completion commit. |

## Drift check

Before editing, check the task's `modifies`, `creates`, and both paths in each
`renames` entry against the working tree. Uncommitted or unexpected changes,
or an existing `creates` path, are drift. Note benign drift and proceed; drift
that invalidates the task's assumptions is a blocker.

## Testing

Use the verification approach the independent pre-edit review approved (in
your brief); record any alternative and its reason.
Run lint and only the assigned task's `#### Verification` checks. The
orchestrator handles reviews, full suites and generated-file refreshes.

Profiles: `tdd`, `regression`, `characterization`, `smoke`, and
`not-applicable` (run the named structural checks and say why).

- Map each `#### Verification` check to a coverage area and write the test that
  best expresses it. A check that resists any coverage means the task is
  mis-scoped: mark it blocked and stop.
- Take expected values from an independent source of truth (a known-good
  literal, a worked example, the spec), never recomputed the way the code
  does.
- Outside `refactor` posture, leave refactoring to the plan-level simplify
  pass at finish.

## While editing

- Check a shared surface's dependents first.
- Format owned files only (Rust: `rustfmt --edition <crate edition> <file>`,
  never `cargo fmt`); rustfmt also formats out-of-line `mod` children, so
  check every touched path afterward.
- In a shared-checkout wave, edit only owned paths and run no state-changing
  Git command (`add`, `commit`, `stash`, `restore`, `checkout`, `reset`,
  `clean`). Report status, verification evidence, every touched path and
  `git hash-object` for each owned file. If a check is blocked by a sibling's
  in-progress or failed change, report `waiting: sibling failure` with the
  check and observed output; the orchestrator reruns that check after the
  wave.
- A file you must write outside `modifies`/`creates`/`renames` is a blocker:
  stop and report it rather than widening the task; a sibling executor may
  own it.
- A UI check needs a browser tool from your own tool list, else it is
  `unavailable`; never infer rendering from HTTP or source. Log in only with
  credentials the user supplied, and submit no form that changes real data.

## Blockers

For every posture, stop after two failed attempts at one approach and report the task `blocked`.

| Execution | On a blocker |
|---|---|
| Serial or inline, in the owning approval checkout | Run `varde-workflow transition <task.md> blocked --json`, log the reason in `#### Progress`, and stop. |
| Parallel worker or isolated execution worktree | Report `blocked`, the reason, and verification evidence without editing the task file; the parent records task state and Progress. |

## Completion

1. After source edits outside `<working>`/`<knowledge>`, run the project's
   configured lint or scan tooling. Its findings are candidates, not a gate:
   fix real issues; skip false positives and rules flagging correct code.
2. Verify every `#### Verification` check: each `assert:` command must match
   its stated expectation, and each `retrieve:` command's output must be read.
3. In serial or inline execution, end `#### Progress` with a completion entry
   naming the checks actually run and leave the task `in_progress`; the
   orchestrator moves it to `done` after its ownership check. In a parallel
   worker or isolated worktree, edit no task file: report that evidence and
   the parent transitions the task.
4. For a spike, commit no source changes: record question/approach/answer and
   restore your own exploratory source edits before reporting. Otherwise,
   commit only task source paths with a message referencing the task ID in
   serial, inline or worktree execution; in a shared-checkout wave, do not
   commit. Undo a completed implementation task with `git revert`.
5. Report the result and any obstacle, and paste raw output from:
   ```sh
   git log --oneline -1
   git status --short
   grep -m1 '^status:' <task.md>
   ```
   Reproduce any failure called pre-existing at the plan's base commit and
   paste that output.
