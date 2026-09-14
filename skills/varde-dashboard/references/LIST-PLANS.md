# Panel: Plans

1. Glob `memory-bank/working/plans/*/plan.md` and read each one's
   frontmatter `status`.
2. Keep only plans in a **non-terminal status** — anything except
   `completed` or `archived`.
3. Sort by recency using the date prefix on the plan ID
   (`<YYYY-MM-DD>-<slug>`), most recent first. Plans with a legacy numeric
   ID (no date prefix) sort last.
4. Take the top 5. For each, derive Tasks/Done counts from its task files:
   total task files under `tasks/*.md` and how many have `status: done`.
5. Present:

   ```
   Plans (non-terminal, most recent 5):

   | Status | Plan | Tasks | Done |
   |--------|------|-------|------|
   | active   | 2026-08-10-manage-command | 5 | 3 |
   | backlog  | 2026-08-09-mcp-tool-slim-pass | 2 | 0 |
   ```

6. If more than 5 plans matched the filter, add a line after the table:
   ```
   +<N> more non-terminal plans not shown.
   ```
7. If none matched, output `No plans in a non-terminal status.` and skip
   the table.
