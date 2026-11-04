# Widget matrix: rich chart

Each chart type as the chart component draws it.

```ui
c-bar = chart(
  kind: "bar",
  title: "Latency by build",
  unit: "ms",
  desc: "The p95 latency halves after the cache change while p50 drops by a third.",
  labels: ["before", "cache", "index", "after"],
  series: [
    {"name": "p50", "values": [120, 95, 88, 80]},
    {"name": "p95", "values": [400, 310, 260, 210]},
  ],
  notes: [{"x": "cache", "label": "cache on"}],
)
```

```ui
c-stack = chart(
  kind: "bar",
  title: "Requests by outcome",
  unit: "k",
  stack: true,
  labels: ["Mon", "Tue", "Wed", "Thu", "Fri"],
  series: [
    {"name": "ok", "values": [40, 52, 47, 60, 58]},
    {"name": "retried", "values": [6, 4, 9, 5, 7]},
    {"name": "failed", "values": [2, 1, 3, 1, 2]},
  ],
)
```

```ui
c-horizontal = chart(
  kind: "bar",
  title: "Bundle size",
  unit: "kB",
  horizontal: true,
  labels: ["core", "charts", "tables", "diagrams"],
  series: [{"name": "gzip", "values": [34, 18, 22, 41]}],
)
```

```ui
c-line = chart(
  kind: "line",
  title: "Weekly signups",
  labels: ["W1", "W2", "W3", "W4", "W5", "W6"],
  series: [
    {"name": "web", "values": [120, 150, 170, 160, 210, 260]},
    {"name": "mobile", "values": [80, 90, 140, 180, 190, 230]},
  ],
  notes: [{"x": "W4", "label": "launch"}],
)
```

```ui
c-area = chart(
  kind: "area",
  title: "Memory",
  unit: "MB",
  labels: ["0s", "10s", "20s", "30s", "40s"],
  series: [{"name": "heap", "values": [210, 260, 240, 330, 300]}],
)
```

```ui
c-scatter = chart(
  kind: "scatter",
  title: "Size against time",
  unit: "s",
  series: [
    {"name": "small", "x": [1, 2, 3, 4], "values": [0.4, 0.9, 1.1, 1.9]},
    {"name": "large", "x": [2, 4, 6, 8], "values": [1.5, 3.1, 4.4, 6.2]},
  ],
)
```

```ui
c-donut = chart(
  kind: "donut",
  title: "Where the time goes",
  unit: "ms",
  labels: ["parse", "layout", "paint", "script"],
  series: [{"name": "time", "values": [30, 55, 25, 90]}],
)
```

```ui
c-spark = chart(
  kind: "sparkline",
  title: "Errors per hour",
  labels: ["1h", "2h", "3h", "4h", "5h", "6h"],
  series: [{"name": "errors", "values": [3, 5, 2, 8, 4, 1]}],
)
```

```ui
c-combo = chart(
  kind: "combo",
  title: "Revenue and margin",
  unit: "k",
  right_unit: "%",
  labels: ["Q1", "Q2", "Q3", "Q4"],
  series: [
    {"name": "revenue", "values": [120, 150, 170, 210]},
    {"name": "margin", "values": [18, 22, 20, 27], "axis": "right"},
  ],
)
```

```ui
c-negative = chart(
  kind: "bar",
  title: "Change against plan",
  unit: "%",
  labels: ["north", "south", "east", "west"],
  series: [{"name": "delta", "values": [-4.5, 3, 0, -1.2]}],
)
```
