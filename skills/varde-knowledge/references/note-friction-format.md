# Item format

New items use this frontmatter:

```yaml
type: friction-item
source: <skill, task, or manual-review source>
status: open
signal: <obstacle | positive>
created: <YYYY-MM-DD>
head_sha: <short HEAD SHA at capture, or `none` outside Git>
session_label: <session name or sanitized first prompt, maximum 46 characters>
```

Older items may omit `signal`. Treat those as `obstacle` items.
Use `positive` for a useful technique or confirmed choice.

Only reconcile may change a status. The lifecycle is `open`, then `resolved`,
then `archived`.

Use the body for the event, evidence, cost, workaround,
and possible improvement. Keep unrelated events separate.

## Creating a new item

If no matching open item exists, create a file under
`memory-bank/friction/`. Use a short kebab-case name.

Example: `memory-bank/friction/stale-build-command.md`.

## Appending to an existing item

If an open item matches, append a new occurrence to that file, leaving its
frontmatter and earlier entries as they are.

Start each new occurrence with:

```markdown
- <YYYY-MM-DD> · <short HEAD SHA> · <session_label>
```

Then describe that occurrence below the line.

Use `Glob`, `Grep`, and `Read` for discovery.
Use `Write` or `Edit` for changes.
