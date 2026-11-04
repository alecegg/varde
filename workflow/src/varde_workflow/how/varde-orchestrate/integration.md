---
topic: varde-orchestrate/integration
version: 1
summary: Merge slot, batch checks, and integrating task commits
---

## Integrate

- Workers do not merge.
- Request the merge slot from main by `info`; after `info: slot granted` and an empty `git status --short` in the main checkout, merge with `varde plan merge <PLAN>`; notify main when done.
- Run the batch check with `bash scripts/worktree-wave.sh integrate <plan>-<wave> --check <command>`; it bisects failures to a culprit task. Build branch `varde` with `uv sync --locked --all-packages` before `--check` (missing only warns); it runs each modified package's unfiltered tests.
- At wrap-up, the orchestrator or merge agent runs full workspace/integration checks under the repository lock; workers never do.
- Use `release --keep` for clean workers; report dirty or unmerged workers in place.
- Commits to the plan branch/task worktrees are authorized; other targets and pushes need explicit user approval.
- On conflict or failed integration checks, preserve the verified prefix/remainder and report evidence.
