# Optional `varde-workflow` CLI

Optional; adds ranked search over the same files. Write notes with Write/Edit
whether or not it is installed.

## Search

A bundle is a directory of concept `.md` files; a slug is the bundle-relative
path without `.md`, such as `pattern/code-review`.

```bash
BUNDLE=<knowledge>

# Ranked full-text over bodies and frontmatter; --field narrows first.
varde-workflow concept search --bundle "$BUNDLE" --text "<query>" --limit 10
varde-workflow concept search --bundle "$BUNDLE" --field type=decision --text "<query>"
```

`--bundle` scopes the search to that bundle alone. Read the full note
before acting on a result.

## Fallback rule

Sandbox denial: retry once with escalated access, command unchanged; if that
fails, or the CLI errors, use Read/Grep and Write/Edit and name the lost
capability once.

A command that answers `ok: false` with a validation code is a result, not an
outage: fix the cause instead of routing around it.

Never build or install the binary during another workflow.
