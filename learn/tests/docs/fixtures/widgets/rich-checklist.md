# Widget matrix: rich checklist

An acceptance list with the three states, notes and inline code.

```ui
c1 = checklist(
  title: "Acceptance criteria",
  items: [
    {"label": "Queue keeps insertion order", "status": "done"},
    {"label": "Retry waits with `backoff`", "checked": true, "note": "Covered by test_retry."},
    {"label": "Docs name the new flag"},
    {"label": "Migration runs on SQLite 3.40", "status": "blocked", "note": "Waiting on the CI image."},
    {"label": "Release notes drafted", "status": "open"},
  ],
)
```

```ui
c2 = checklist(
  items: [{"label": "Only item", "status": "done"}],
)
```
