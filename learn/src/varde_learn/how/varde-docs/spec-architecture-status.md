---
topic: varde-docs/spec-architecture-status
version: 1
summary: Act on the inventory architecture_status value
---

| Inventory `architecture_status` | Action |
|---|---|
| `none` | Inspect `architecture_candidates` first; a candidate can be a deployment or workspace declaration the inventory cannot identify by filename. |
| `inspect` | Read each `architecture_inspect_paths` entry. Refresh architecture if it affects deployed units or wiring; otherwise acknowledge the path with `varde learn docs spec` (the CLI binds its current content hash). |
