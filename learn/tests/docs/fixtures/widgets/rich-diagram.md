# Widget matrix: rich diagram

A request path and a small tree, as the diagram component draws them.

```ui
d1 = diagram(
  kind: "graph",
  title: "Request path",
  desc: "A user request through the gateway to the API and database, with a retry loop and an audit branch.",
  direction: "LR",
  groups: [{"id": "edge", "label": "Edge"}, {"id": "core", "label": "Core services"}],
  nodes: [
    {"id": "user", "label": "User", "shape": "rounded", "detail": "A person at a browser or phone."},
    {"id": "gw", "label": "Gateway", "group": "edge", "detail": "Terminates TLS and rate limits."},
    {"id": "auth", "label": "Valid token?", "group": "edge", "shape": "diamond"},
    {"id": "api", "label": "API server", "group": "core", "detail": "Stateless; scales out."},
    {"id": "db", "label": "Database", "group": "core", "shape": "cylinder", "detail": "Primary with one replica."},
    {"id": "log", "label": "Audit log", "shape": "cylinder"},
  ],
  edges: [
    {"from": "user", "to": "gw", "label": "https"},
    {"from": "gw", "to": "auth"},
    {"from": "auth", "to": "api", "label": "yes"},
    {"from": "auth", "to": "user", "label": "no: 401", "style": "dashed"},
    {"from": "api", "to": "db", "label": "sql"},
    {"from": "api", "to": "api", "label": "retry", "style": "dotted"},
    {"from": "api", "to": "log", "style": "dashed"},
  ],
)
```

```ui
d2 = diagram(
  kind: "tree",
  title: "Release tree",
  nodes: [
    {"id": "root", "label": "Release 2.0"},
    {"id": "app", "label": "App", "detail": "Mobile and web clients."},
    {"id": "svc", "label": "Services"},
    {"id": "web", "label": "Web", "shape": "rounded"},
    {"id": "ios", "label": "iOS", "shape": "rounded"},
    {"id": "api", "label": "API"},
    {"id": "jobs", "label": "Jobs"},
  ],
  edges: [
    {"from": "root", "to": "app"}, {"from": "root", "to": "svc"},
    {"from": "app", "to": "web"}, {"from": "app", "to": "ios"},
    {"from": "svc", "to": "api"}, {"from": "svc", "to": "jobs"},
  ],
)
```
