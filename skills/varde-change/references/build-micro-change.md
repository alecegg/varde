# Build a micro-change

Use this branch only for clear, bounded changes.
Examples include renaming one label or adjusting one behavior.

1. Read applicable repository instructions.
2. Inspect the target and its narrow verification together.
3. Name that check and its expected pass result before editing.
   When the expected result cannot be stated in advance, this is not a
   micro-change; use `references/plan.md` instead.
4. Edit only the requested behavior.
5. Run the named check and compare its actual result to the expected one.
6. Report changed files and verification evidence.

Do not create plans, tasks, worktrees, or handoffs.
Do not commit unless the user explicitly requests it.
Stop after reporting the completed change.
Batch independent reads and verification within single tool calls.
When several files or symbol relationships matter, combine its index build and
`varde-code batch` within one shell call.
Request target symbols and covering tests together.
Use that context instead of separate reads and greps.
For one short, known file, use one targeted read instead.
Fall back when unavailable or unsuccessful.
