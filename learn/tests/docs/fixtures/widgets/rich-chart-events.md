# Widget matrix: rich chart events

Tone bands and markers on line, bar and scatter charts.

```ui
ce-line = chart(
  kind: "line",
  title: "Latency over a release",
  unit: "ms",
  desc: "Latency rises during the rollout band and recovers after the fix marker.",
  labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  series: [
    {"name": "p50", "values": [80, 82, 120, 140, 90, 84]},
    {"name": "p95", "values": [210, 220, 380, 410, 250, 215]},
  ],
  notes: [
    {"from": "Tue", "to": "Thu", "label": "rollout", "tone": "warning"},
    {"x": "Fri", "label": "fix shipped", "tone": "success"},
    {"x": "Wed", "label": "decision", "tone": "decision"},
  ],
)
```

```ui
ce-bar = chart(
  kind: "bar",
  title: "Requests by week",
  unit: "k",
  labels: ["W1", "W2", "W3", "W4", "W5"],
  series: [{"name": "requests", "values": [40, 52, 47, 60, 58]}],
  notes: [
    {"from": "W2", "to": "W3", "label": "freeze", "tone": "risk"},
    {"from": "W1", "to": "W5", "label": "quarter"},
    {"x": "W4", "label": "launch", "tone": "info"},
  ],
)
```

```ui
ce-scatter = chart(
  kind: "scatter",
  title: "Size against time",
  series: [
    {"name": "builds", "x": [1, 2, 3, 4, 5, 6, 7, 8], "values": [3, 4, 6, 5, 9, 8, 12, 11]},
  ],
  notes: [
    {"from": 3, "to": 5, "label": "slow window", "tone": "warning"},
    {"x": 7, "label": "cache", "tone": "success"},
  ],
)
```

```ui
ce-old = chart(
  kind: "line",
  title: "Plain notes stay as they were",
  labels: ["a", "b", "c"],
  series: [{"name": "s", "values": [1, 3, 2]}],
  notes: [{"x": "b", "label": "peak"}],
)
```
