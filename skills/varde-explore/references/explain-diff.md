# Diff explanation

Use when the target is a git ref: branch, commit range, or PR reference.

1. Resolve the target to a concrete diff before running `git diff`:
   - Branch: run `git diff <branch>`. Include `--stat` and the full patch as
     needed to identify the changed files.
   - Commit range: run `git diff abc..def`.
   - PR reference (`pr/123`, `#123`): you cannot pass this reference directly
     to `git diff`. Resolve it first. Prefer `gh pr diff <n>` when the GitHub
     CLI is available. Otherwise fetch the PR head ref (`git fetch
     origin pull/<n>/head:pr-<n>`) and diff it against its base branch
     (`git diff <base>...pr-<n>`). Use the PR's merge target as its base, not
     the current checkout.
2. Read changed hunks and short, known files directly. Load
   `references/varde-code.md` for callers, callees, or cross-file impact.
   Batch related lookups. Use `get_symbol` only for an exact symbol inside a
   large file. Otherwise, use `Grep` and direct reads.
3. Read the diff hunks for the changed files. Use those hunks, not only the
   files' current contents, to explain the change.
4. Write the HTML output by following workflow step 4.
