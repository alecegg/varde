# Widget matrix: rich matrix

A decision matrix with a recommendation, weights and both rating scales.

```ui
m1 = matrix(
  title: "Queue storage",
  options: [
    {"id": "sqlite", "label": "SQLite", "note": "One writer is enough for this load."},
    {"id": "pg", "label": "Postgres"},
    {"id": "mq", "label": "Message broker", "note": "Adds a service to run."},
  ],
  criteria: [
    {"id": "ops", "label": "Easy to run", "weight": 3},
    {"id": "scale", "label": "Scales out", "weight": 2},
    {"id": "cost", "label": "Low cost"},
  ],
  cells: [["yes", "partial", "no"], ["no", "yes", "yes"], ["yes", "partial", "partial"]],
  recommended: "sqlite",
)
```

```ui
m2 = matrix(
  options: [{"id": "a", "label": "Option A"}, {"id": "b", "label": "Option B"}],
  criteria: [{"id": "speed", "label": "Speed"}, {"id": "risk", "label": "Migration risk"}],
  cells: [["high", "low"], ["medium", "high"]],
)
```

```ui
m3 = matrix(
  options: [{"id": "only", "label": "Only option"}],
  criteria: [{"id": "fit", "label": "Fits the plan"}],
  cells: [["yes"]],
  recommended: "only",
)
```
