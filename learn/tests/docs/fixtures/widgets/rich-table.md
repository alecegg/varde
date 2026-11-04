# Widget matrix: rich table

A normal table with typed columns, a sticky first column and row groups.

```ui
rich-table = table(caption: "Services", columns: ["service", "owner", "latency ms", "load", "state", "docs"], types: {"latency ms": "number", "load": "bar", "state": "status", "docs": "link"}, rows: [["api", "core", 120, 80, "ok", ["Runbook", "https://example.com/api"]], ["db", "data", 45.5, 20, "degraded", ["Runbook", "https://example.com/db"]], ["queue", "core", 9, 50, "failed", ["Runbook", "https://example.com/queue"]], ["cache", "data", 3, 5, "ok", ["Runbook", "https://example.com/cache"]]], footnote: "Latency is the p95 over seven days.", sticky_column: true, stack: true, groups: [{"label": "Core", "rows": 2}, {"label": "Data", "rows": 2}])
```

```ui
rich-table-narrow = table(caption: "Narrow columns", columns: ["id", "status", "method", "type", "code", "notes"], types: {"status": "status"}, rows: [["a1", "ok", "GET", "enum", "200", "A longer free-text note that wraps at word boundaries only and keeps the narrow columns intact on a phone."], ["b2", "failed", "POST", "string", "500", "Another sentence of description that is long enough to need several lines."], ["c3", "pending", "DELETE", "integer", "204", "Short note."]])
```

```ui
rich-table-wide = table(caption: "Ten columns", columns: ["name", "owner", "region", "tier", "state", "cpu", "memory", "disk", "network", "updated"], types: {"state": "status", "cpu": "number", "memory": "number"}, rows: [["api", "core", "eu-west", "gold", "ok", 41, 62, "120 GB", "1 Gbps", "2026-11-01"], ["db", "data", "us-east", "silver", "degraded", 77, 88, "2 TB", "10 Gbps", "2026-11-02"], ["queue", "core", "ap-south", "bronze", "failed", 12, 30, "40 GB", "100 Mbps", "2026-10-30"]])
```
