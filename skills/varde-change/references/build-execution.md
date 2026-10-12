# Execution Reference

Start from the task file named in the brief. It is reference material, not state
to edit. Treat the dispatch brief as context; do not reread the plan. Load
`references/build-posture-debug.md` or `references/build-posture-refactor.md`
only when the task declares that posture.

## Checks

- Write the failing test first for a behavior change, then the fix.
- Test only your slice (task asserts plus unit tests of the changed package,
  and the one changed integration target only if the task edits an integration
  test or a CLI contract); never run the full suite; after a fix rerun only the
  failing target.
- Wrap long builds and tests in `scripts/measure-writes.sh run` and report its
  `writes:` line. Prefer compile-only checks for iteration when available.
- Do not poll a running command or agent; wait on completion or use one long
  wait.
- Stop after two failed attempts at one approach. Reproduce a failure the task
  calls pre-existing at the prerequisite commit.
- Before changing a shared surface, check its dependents. Format only owned
  files; return writes outside the task's paths to the parent.
- Run the task's assert and retrieve checks and compare them with independent
  expected values. For `not-applicable`, run the named structural checks and
  explain why.
- For UI checks, use a browser or report it unavailable; never infer rendering
  from source or HTTP. Use only user-supplied credentials and submit no
  real-data forms.
- The parent runs reviews, full suites, and generated-file refreshes.

Commit only verified task paths with the task ID in the message, and report the
commit, worktree, owned paths, checks, status, and blockers. Do not edit task or
plan state.
