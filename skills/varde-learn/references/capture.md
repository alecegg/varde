# Capture an observed friction event

Record only a problem that actually happened in this session. Do not log a
predicted risk or a general lesson without an observed obstacle.

1. Confirm `varde-learn` is available on `PATH`. If it is missing, report that
   the event cannot be recorded and continue unrelated work. If a command is
   denied by the sandbox, retry it unchanged once with escalated access; if
   that fails, report the recording obstacle. Do not create or edit a Markdown
   friction file as fallback.
2. Search open items for a distinctive phrase from the event:

   ```sh
   varde-learn friction list --status open --text "distinctive phrase" --json
   ```

   The text filter is a case-insensitive literal substring. If the response is
   truncated, fetch later pages with `--offset` and `--limit`; inspect a likely
   match with `varde-learn friction show <ID> --json`. Continue `show` pages
   until `meta.truncated` is false. Append only when it is the same obstacle,
   not merely a related topic.
3. Put the observed evidence on stdin. Append to a matching item by numeric ID:

   ```sh
   printf '%s\n' 'The repeated check failed because ...' | \
     varde-learn friction add --item 42 --json
   ```

   Otherwise create an item with a concise title and the skill or tool that
   exposed the obstacle:

   ```sh
   printf '%s\n' 'The check failed because ...' | \
     varde-learn friction add --source varde-change --title "Missing path check" --target skills/example/SKILL.md --json
   ```

4. New items are scoped to the current repository by default. Add `--global`
   for friction in a cross-project skill or tool; leave repository-specific
   events local. Appending keeps the existing item's scope and status.
5. Check the JSON result and use `friction show <ID> --json` to confirm the
   occurrence was recorded. If the CLI returns an error, report that recording
   failed and continue unrelated work; do not claim success or write a Markdown
   fallback.

Keep the evidence specific: what command or action failed, what happened, and
the immediate cost. The store records repository and Git context when
available; do not invent it in the evidence text.
