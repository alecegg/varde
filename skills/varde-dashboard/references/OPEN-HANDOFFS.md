# Panel: Handoffs

This section is read-only — it drives no lifecycle transition. Resuming and
picking up a handoff belongs to `/varde-handoff`'s resume mode, and link
freshness is not re-verified here: the dashboard displays raw frontmatter
as written, with no staleness re-checking.

1. Glob `memory-bank/working/handoffs/*/handoff.md` and read each one's
   frontmatter. Keep the ones with `status: open`.
2. Sort by `timestamp`, most recent first. Take the top 5.
3. For each of the top 5, scan its `links` array (entries like
   `{target, kind}`) for entries with `kind: plan`, and read each one's
   target plan's `memory-bank/working/plans/<target>/plan.md` frontmatter
   `status` to display inline.
4. If no handoffs match, output:
   ```
   No open handoffs.
   ```
5. Otherwise present:

   | Handoff | Description | Timestamp | Linked plan status |
   |---------|-------------|-----------|--------------------|
   | 2026-08-11-widget-resume | Resume the widget migration | 2026-08-11T09:30:00Z | 2026-08-11-widget-migration (active) |

   Each handoff's ID is its directory name under
   `memory-bank/working/handoffs/`. A handoff with no `kind: plan` links
   gets an em-dash in the last column. If a handoff links several plans,
   list each as `id (status)`.
6. If more than 5 open handoffs matched, add a line after the table:
   ```
   +<N> more open handoffs not shown.
   ```
