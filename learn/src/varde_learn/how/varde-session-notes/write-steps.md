---
topic: varde-session-notes/write-steps
version: 1
summary: Write notes, part 1 of 3 (steps 1-2) - anchor and redaction of secrets; then write-links, write-save
---

# Write session notes: steps

Build session notes as you go, not at the end. If no session notes file
exists, create it from steps 1-4 first.

1. **Capture the session and git anchor.** Record `cwd` from `pwd`. Inside Git,
   also record `repo_root`, `branch`, `head_sha`, and dirty porcelain paths (or
   `[]`); outside Git use exactly `repo_root: none`, `branch: none`,
   `head_sha: none`, and `dirty: not-applicable`.
2. **Redact, then fill the template.** Strip API keys, tokens, passwords,
   connection strings, and personally identifying information, and tailor
   **What's left** and **Suggested next skill** to any focus the user named.
