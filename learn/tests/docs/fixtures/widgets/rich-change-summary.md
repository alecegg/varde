# Widget matrix: rich change-summary

Changes on this page are counted in the line below.

```ui
k1 = change-summary(
  title: "What changed",
)
```

```ui
d1 = data-model(
  entity: [
    {"name": "order", "key": "id", "change": "modified", "fields": {"id": "uuid", "total": {"type": "cents", "change": "added"}, "note": {"type": "text", "change": "removed"}}},
    {"name": "invoice", "key": "id", "change": "added", "fields": {"id": "uuid"}},
  ],
)
```

```ui
e1 = endpoint(
  method: "POST",
  path: "/orders",
  auth: "bearer",
  change: "modified",
  request: {"customer_id": {"type": "uuid", "change": "added"}},
  responses: [
    {"status": 201, "body": "the new order", "change": "added"},
    {"status": 422, "body": "validation errors"},
  ],
)
```

```ui
f1 = file-tree(
  title: "Changed files",
  entries: [
    {"path": "src/queue.py", "change": "modified"},
    {"path": "src/retry.py", "change": "added"},
    {"path": "src/backoff.py", "change": "renamed", "was": "src/wait.py"},
  ],
)
```

```ui
k2 = change-summary()
```
