# Standalone verification

Report aggregate plan evidence without implementing changes. This mode is
read-only: it reads plan and task files and writes none of them, leaving
acceptance checkboxes and task status exactly as it found them.

1. Resolve the requested plan or change target.
2. Read its acceptance criteria and completed tasks.
3. Run declared assertions and relevant project checks.
4. Retrieve required source evidence for judgment.
5. Report passed, failed, and unavailable evidence.

Recommend `varde-change build` when fixes become necessary.
