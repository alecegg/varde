# Widget matrix: rich stats

A headline strip for a service review, with good and bad moves and a flat one.

```ui
s1 = stats(
  item: [
    {"label": "Requests", "value": 1204331, "delta": "12%", "direction": "up", "good": "up"},
    {"label": "p95 latency", "value": "212 ms", "delta": "-8%", "good": "down", "note": "Since the cache change."},
    {"label": "Error rate", "value": 0.4, "decimals": 2, "delta": "0.1 pt", "direction": "up", "good": "down"},
    {"label": "Uptime", "value": "99.98%", "delta": "0%", "direction": "flat"},
    {"label": "Open incidents", "value": 3},
    {"label": "Queue depth", "value": 18250, "delta": -1200, "good": "down", "note": "Drained `retry` lane."},
  ],
)
```

```ui
s2 = stats(
  item: [
    {"label": "Passed", "value": 412, "delta": "5", "direction": "up", "good": "up"},
    {"label": "Failed", "value": 2, "delta": "1", "direction": "down", "good": "down"},
  ],
)
```
