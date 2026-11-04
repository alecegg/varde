# Execution Reference

Take context from the task file named in the brief. Commit only when the task
or existing user authorization permits it.

## Checks

- Run only your slice's checks, never the full suite.
- Format only owned files; return writes outside the task's paths to the parent.
- Run the task's assert and retrieve checks and report the results.
- For UI checks, use a browser or report it unavailable; never infer rendering
  from source or HTTP. Use only user-supplied credentials and submit no
  real-data forms.
- The parent runs reviews, full suites, and generated-file refreshes.

Commit only verified task paths, with the task ID in the message. Report the
commit, worktree, owned paths, checks, status, and blockers. Do not edit task or
plan state.
