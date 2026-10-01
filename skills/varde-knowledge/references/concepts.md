# Concept search and maps

A bundle is a directory of concept `.md` files. A slug is the bundle-relative
path without `.md`, such as `pattern/code-review`.

```bash
BUNDLE=<knowledge>
varde-workflow concept search --bundle "$BUNDLE" --text "<query>" --limit 10
varde-workflow concept search --bundle "$BUNDLE" --field type=decision --text "<query>"
```

Read a full note before acting on a search result.

## Concept maps

For broad navigation, read the generated root and type `index.md` maps. If
they are missing or stale after Concept changes, regenerate them:

```bash
varde-workflow concept map --bundle "$BUNDLE"
```
