# Reconcile a friction item against evidence

Reconciliation checks whether an existing obstacle is resolved or obsolete.
An item's recorded summary is not proof that the problem is fixed.

1. Read the complete item and its occurrence history:

   ```sh
   varde-learn friction show <ID> --json
   ```

   `show` pages occurrences and status history together. Continue with
   `--offset` until `meta.truncated` is false.
2. For each Git occurrence, use its recorded `repo_root` and `head_sha`.
   Confirm the root with `git -C <repo_root> rev-parse --show-toplevel` and
   verify the recorded commit with
   `git -C <repo_root> cat-file -e '<head_sha>^{commit}'`. If either check
   fails, report that the occurrence cannot be verified. Inspect the named
   source at that commit and compare it with current source or other current
   evidence. A `git log` result alone does not establish that the obstacle is
   fixed.
3. For an occurrence without Git context, use named current evidence such as a
   present file, command result, or user-provided observation. Do not invent a
   repository or SHA, or use Git history to fill the gap.
4. State which occurrences the evidence covers and propose `resolved` or
   `archived`. Ask the user to confirm the status change; leave the item
   unchanged while evidence is missing or confirmation is pending.
5. After confirmation, record the reason through the CLI:

   ```sh
   varde-learn friction set-status 42 resolved --reason "The current check now verifies the required path." --json
   ```

The status command appends an audit event. Do not edit exported Markdown or
the SQLite database directly.
