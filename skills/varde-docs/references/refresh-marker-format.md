## Marker format

Each tracked document starts with:

```text
<!-- docs:v1 {"specs":{"specs/<concept>":"<source_hash>"}} -->
```

The marker lists every source for the document, and a new marker carries the
generated spec's current `source_hash`.

Three cases resolve **stale without failure** — the doc gets regenerated, nothing
errors: a legacy path-style value (still parseable), a missing declared spec, and
an unmatched `source_hash`.

This skill owns the marker. On a later run, read it and rewrite only its managed
sections.
