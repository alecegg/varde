## Marker format

Each tracked document starts with:

```text
<!-- docs:v1 {"specs":{"specs/<concept>":"<source_hash>"}} -->
```

Use the marker to list every source for the document. A new marker carries the
generated spec's current `source_hash`.

Treat these three cases as **stale without failure**: regenerate the document
and report no error. The cases are a legacy path-style value (still parseable),
a missing declared spec, and an unmatched `source_hash`.

On a later run, read the marker and rewrite only its managed sections.
