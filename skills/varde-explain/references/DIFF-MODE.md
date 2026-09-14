# Diff mode

Trigger: target is a git ref (branch, commit range, or PR reference).

1. Resolve the target to a concrete diff before running `git diff`:
   - Branch: run `git diff <branch>` (with `--stat` and full patch as
     appropriate) to determine the changed files.
   - Commit range: run `git diff abc..def`.
   - PR reference (`pr/123`, `#123`): this is not a directly executable
     `git diff` target. Resolve it first — prefer `gh pr diff <n>` when the
     GitHub CLI is available; otherwise fetch the PR head ref (`git fetch
     origin pull/<n>/head:pr-<n>`) and diff it against its base branch
     (`git diff <base>...pr-<n>`). The PR's base is its merge target, not
     the current checkout.
2. For each changed source file, run the proactive context gathering (see
   step 2 of the workflow). When `varde-code` is available
   (`references/VARDE-CODE-CLI.md`), use `get_symbol`/`symbols_in_file`
   (`includeBody`) for the changed symbols' content and `explore`
   (`direction: "both"`) from each changed file for callers/callees — this
   is what "the callers/callees the change affects" in the Code section
   needs. Otherwise `Grep`/`Glob` for symbol references and importers, then
   `Read` the file directly.
3. Read the diff hunks for the changed files so the explanation is grounded in
   the actual change, not just the files' steady state.
4. Proceed to write the HTML output (workflow step 4).
