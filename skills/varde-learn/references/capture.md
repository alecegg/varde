# Capture an observed friction event

Record only a problem that actually happened in this session. Do not log a
predicted risk or a general lesson without an observed obstacle.

1. Search open items for a distinctive phrase from the event:

   ```sh
   varde-learn friction list --status open --text "distinctive phrase" --json
   ```

   Read likely matches with `varde-learn friction show <ID> --json`.
   Append only for the same obstacle, not merely a related topic.
2. Put the observed evidence on stdin. Append to a matching item by numeric ID:

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

3. New items are scoped to the current repository by default. Add `--global`
   for friction in a cross-project skill or tool; leave repository-specific
   events local.

Keep the evidence specific: what command or action failed, what happened, and
the immediate cost. The store records repository and Git context when
available; do not invent it in the evidence text.
