---
format: "varde-friction-item"
version: 1
id: 1
slug: "golden"
title: "Golden"
source: "pytest"
repo_root: "/repo"
status: "promoted"
target: "docs/guide.md"
tags: ["golden"]
created_at: "2025-01-01T00:00:00.000Z"
occurrences:
  - id: 1
    item_id: 1
    at: "2025-01-01T00:00:00.000Z"
    cwd: "/golden/work"
    repo_root: "/repo"
    head_sha: "abc"
    evidence: "first evidence"
    cost: null
  - id: 2
    item_id: 1
    at: "2025-01-01T00:00:06.000Z"
    cwd: "/golden/work"
    repo_root: "/repo"
    head_sha: "abc"
    evidence: "again"
    cost: null
status_changes:
  - id: 1
    item_id: 1
    at: "2025-01-01T00:00:02.000Z"
    from_status: "open"
    to_status: "resolved"
    reason: "fixed"
  - id: 2
    item_id: 1
    at: "2025-01-01T00:00:03.000Z"
    from_status: "resolved"
    to_status: "promoted"
    reason: "Recorded adoption 1"
---

# Friction item 1

## Title

```text
Golden
```

## Occurrences

### Occurrence 1

- Recorded: 2025-01-01T00:00:00.000Z
- Repository: /repo
- Evidence:

```text
first evidence
```

### Occurrence 2

- Recorded: 2025-01-01T00:00:06.000Z
- Repository: /repo
- Evidence:

```text
again
```

## Status history

### Change 1: open → resolved

- Recorded: 2025-01-01T00:00:02.000Z
- Reason:

```text
fixed
```

### Change 2: resolved → promoted

- Recorded: 2025-01-01T00:00:03.000Z
- Reason:

```text
Recorded adoption 1
```

