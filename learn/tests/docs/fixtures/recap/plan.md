---
title: demo
shared:
  - docs/shared.md
  - "**/CHANGELOG.md"
---

```ui id=order-model
order-model = data-model(entity: [{"name": "order", "key": "id", "fields": {"id": "uuid"}}])
```

```ui id=order-flow
order-flow = flow(covers: ["t1"], step: [{"id": "a", "text": "a"}])
```

```ui id=lonely
lonely = table(columns: ["a"], rows: [["x"]])
```
