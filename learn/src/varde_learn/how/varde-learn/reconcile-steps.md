---
topic: varde-learn/reconcile-steps
version: 1
summary: Ordered steps to reconcile a friction item against evidence
---

1. Read the item and its occurrence history with:

   ```sh
   varde learn friction show <ID> --json
   ```
2. For each Git occurrence, verify `repo_root` with `git -C <repo_root> rev-parse --show-toplevel` and `head_sha` with `git -C <repo_root> cat-file -e '<head_sha>^{commit}'`. If either fails, report it as unverifiable; otherwise compare the named source at that commit with current source or evidence. `git log` alone does not establish a fix.
3. For an occurrence without Git context, use named current evidence such as a
   present file, command result, or user-provided observation. Do not invent a
   repository or SHA, or use Git history to fill the gap.
4. State which occurrences the evidence covers and whether `resolved` or
   `archived` fits. Update only when explicitly requested and evidence supports
   one status. Ask when evidence is missing or ambiguous, or the action is
   destructive. Preserve the user's stated reason for a correction.
5. When authorized and supported, record the reason through the CLI:

   ```sh
   varde learn friction set-status 42 resolved --reason "The current check now verifies the required path." --json
   ```
