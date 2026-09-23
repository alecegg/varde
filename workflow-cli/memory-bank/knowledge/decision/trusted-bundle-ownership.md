---
id: decision/trusted-bundle-ownership
type: decision
status: accepted
description: CRUD assumes trusted, stable bundle directory ownership.
generated:
  by: codex/gpt-5.6
  at: 2026-09-21T16:29:07Z
verified:
  - by: human:alec
    at: 2026-09-21T16:29:07Z
paths:
  - README.md
  - okf-core/src/lib.rs
  - okf-core/src/crud.rs
  - okf-core/src/crud/delete.rs
enriched_at_commit: null
---

## What

CRUD assumes trusted ownership of bundle directory topology.
This includes bundle ancestors and nested concept directories.

## Why

Slug validation rejects traversal and existing symlink escapes.
Containment checks only observe one filesystem moment.
They cannot prevent concurrent hostile directory replacement.

## Constraints

- Treat containment checks as defense in depth.
- Do not expose untrusted bundle directory ownership.
- Use descriptor-relative operations if requirements change.
