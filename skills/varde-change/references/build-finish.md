# Finish a built plan

After all tasks finish, the orchestrator reviews implementation, resolves
findings, and completes the checklist on the plan worktree.

## Implementation review

1. Record `base`, the commit from which the plan branch started.
2. Dispatch an independent reviewer over `<base>..HEAD`, with plan, tasks,
   and resolved paths. Load `varde-review` (skill tool or
   `../../varde-review/SKILL.md`); it writes `<plan-dir>/review.md` in the
   required format. For skill/agent-doc edits, it also runs doc-authoring review.
3. With no independent reviewer, stop.

## Resolve findings

Load `varde-review` (skill tool or `../../varde-review/SKILL.md`) and apply its
fix workflow. The user decides grouped intended-behaviour changes.

## End-state checklist

- [ ] Every acceptance criterion passes: run each `assert:` and inspect each
      `retrieve:`.
- [ ] Module changelogs updated for user-visible changes.
- [ ] The merged HEAD carries an approved verdict: the orchestrator runs
      `varde plan conclude <plan-dir>` from the plan worktree (or with
      `--repo`) and resolves its blockers.
- [ ] Branch, base, checks, and remaining concerns reported.
- [ ] Merge only on the user's explicit approval. Sync and conclude wait for
      the approval relayed per `references/build-orchestrate-tasks.md`.
- [ ] Clean up the merged plan worktree.
- [ ] Push or open a PR only after the user's choice is relayed.
- [ ] Reinstall the CLI when the plan changed it.

For concluded plan material being removed, load `varde-knowledge`: use your
skill tool, or read `../../varde-knowledge/SKILL.md`; follow its distillation
route before `git rm`.

## Retro

After the run, the orchestrator records friction not already recorded (worker
reports list the friction ids), including `friction:` sections from reviewer
reports; load `varde-learn`: use your skill tool, or read
`../../varde-learn/SKILL.md`, and propose improvements.
