## Marker format

Each tracked document starts with:

```text
<!-- docs:v1 {"specs":{"specs/<concept>":"<source_hash>"}} -->
```

The marker declares the complete source-to-document mapping. When a spec has a
`source_hash` in its own frontmatter, use its current value when constructing a
new marker; otherwise use any stable identifier for the source (e.g. a short
description of the tracked files). The marker is read and rewritten by the LLM
running this skill, not by any external tool — when re-running the skill, read
the marker to see which sections are auto-managed, and rewrite only those
sections yourself.
