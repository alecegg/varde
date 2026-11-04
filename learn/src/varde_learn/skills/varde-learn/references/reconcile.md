# Reconcile a friction item against evidence

Outcome: a status decision backed by named evidence for each occurrence.

- Verify each Git occurrence: `git -C <repo_root> rev-parse --show-toplevel` for `repo_root` and `git -C <repo_root> cat-file -e '<head_sha>^{commit}'` for `head_sha`. If either fails, report it as unverifiable; otherwise compare the named source at that commit with current source or evidence. `git log` alone does not establish a fix.
- For an occurrence without Git context, use named current evidence such as a present file, command result, or user-provided observation. Do not invent a repository or SHA, or use Git history to fill the gap.
- State which occurrences the evidence covers and whether `resolved` or `archived` fits.
- Update only when explicitly requested and evidence supports one status. Ask when evidence is missing or ambiguous, or the action is destructive. Preserve the user's stated reason for a correction.
- Record the status through the CLI with a reason: `varde learn friction set-status <ID> <status> --reason "<reason>" --json`.
- Do not edit exported Markdown or the SQLite database directly.
