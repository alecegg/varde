# Reconcile a friction item against evidence

1. Read the complete item and its occurrence history:

   ```sh
   varde-learn friction show <ID> --json
   ```
2. For each Git occurrence, use its recorded `repo_root` and `head_sha`.
   Confirm the root with `git -C <repo_root> rev-parse --show-toplevel` and
   the commit with `git -C <repo_root> cat-file -e '<head_sha>^{commit}'`; if
   either fails, report the occurrence as unverifiable. Otherwise compare the
   named source at that commit with current source or evidence; a `git log`
   result alone does not establish a fix.
3. For an occurrence without Git context, use named current evidence such as a
   present file, command result, or user-provided observation. Do not invent a
   repository or SHA, or use Git history to fill the gap.
4. State which occurrences the evidence covers and whether `resolved` or
   `archived` fits. An explicit user request to reconcile or update the item
   authorizes an evidence-supported, unambiguous status. Ask when evidence is
   missing, more than one status fits, or the action is destructive.
5. When authorized and supported, record the reason through the CLI:

   ```sh
   varde-learn friction set-status 42 resolved --reason "The current check now verifies the required path." --json
   ```

Do not edit exported Markdown or the SQLite database directly.
