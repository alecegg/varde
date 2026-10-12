# Execution Reference

## Startup

When dispatched with a brief, it is your plan context; do not read `plan.md`
or the orchestrator's build reference.
In your first turn, run the start or resume check below, the drift check, and
any posture reference load together, and read your task file for reference
only. Use the brief's orientation before searching.

## Review checks

These checks are your whole review gate; skip `references/review-gates.md`.
The parent passes the plan subject id and resolved memory paths. Tasks inherit
that subject and its approved verdict; never initialize or record approval
yourself.

1. Before the first edit, run:

   ```sh
   varde work review check --subject <subject-id> --checkpoint start --json
   ```

2. Before continuing interrupted work, run it with `--checkpoint resume`.
3. On exit 3 (OCC conflict), rerun the check. On exit 4 (a typed blocker),
   stop and return it to the caller.
4. Material drift from the approved scope or verification returns to the
   caller for a fresh verdict.

A verified task may be `done` with the aggregate implementation review
pending; the plan stays incomplete.

## Separate execution checkout

Every writing task uses a fresh execution worktree, including serial and
inline tasks. Load `references/build-worktree.md` and add the caller-supplied
binding to start/resume checks: `--repository <approval-checkout>`, `--worktree
<absolute-worker-path>`, and `--binding <task-binding-id>` together. Stop if
that context is missing or rejected.

### First worker action

Before source edits, run `python3 <absolute-helper> check` using the brief's
absolute path to `scripts/worktree-permissions.py` and its repository, worktree,
subject, and binding flags from the exact worker cwd in its actual sandbox. This includes the bound start check. Do not
escalate a failed worker preflight; return its evidence so the caller can
correct the launch permissions.

## Task kind and posture

| Task | Before the first edit |
|---|---|
| `kind: research` | Write the `creates` doc from primary sources outside the repo, citing each claim (URL, spec section, file:line); a decision ends with one recommendation. Then run Completion. |
| `debug` posture | Load `references/build-posture-debug.md`; keep `debug_evidence` per its Evidence contract. |
| `refactor` posture | Load `references/build-posture-refactor.md`. |

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
- Outside `refactor` posture, leave refactoring to the review's SIMPLICITY
  category.

## While editing

- Check a shared surface's dependents first.
- Format owned files only.
- Edit only owned paths in the supplied task worktree. Commit verified source
  locally under the caller's explicit plan/bounded-change authorization.
- A file you must write outside `modifies`/`creates`/`renames` is a blocker:
  stop and report it rather than widening the task; a sibling builder may
  own it.
- A UI check needs a browser tool from your own tool list, else it is
  `unavailable`; never infer rendering from HTTP or source. Log in only with
  credentials the user supplied, and submit no form that changes real data.

## Blockers

For every posture, stop after two failed attempts at one approach and report the task `blocked`.

| Execution | On a blocker |
|---|---|
| Any task worktree | Report `blocked`, the reason, and verification evidence without editing the task file; the parent records state and Progress at the approval checkout. |

## Completion

1. After source edits outside `<working>`/`<knowledge>`, run the project's
   configured lint or scan tooling. Its findings are candidates, not a gate:
   fix real issues; skip false positives and rules flagging correct code.
2. Verify every `#### Verification` check: each `assert:` command must match
   its stated expectation, and each `retrieve:` command's output must be read.
3. Report completion evidence without editing task files; the orchestrator
   records Progress and moves the task to `done` after ownership, integration,
   and binding release.
4. Commit only task source paths with the task ID in the message. Undo a
   completed implementation task with `git revert`.
5. Report the commit, owned paths, worktree path, checks, and obstacles. Give
   short `git status --short` output; link logs instead of pasting full diffs
   or verification output. Reproduce a failure called pre-existing at the
   prerequisite commit and report that evidence.
