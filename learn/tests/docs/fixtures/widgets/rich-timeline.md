# Widget matrix: rich timeline

A rollout in phases, vertical by default, then a horizontal row that scrolls.

```ui
t1 = timeline(
  title: "Rollout plan",
  item: [
    {"when": "Week 1", "label": "Design review", "status": "done", "owner": "Design"},
    {"when": "Week 2", "label": "Build the importer", "status": "done", "note": "Ran against `staging` data."},
    {"when": "Week 3", "label": "Pilot with two teams", "status": "active", "owner": "Platform", "note": "Feedback due Friday."},
    {"when": "Week 4", "label": "Fix pilot findings", "status": "blocked", "note": "Waiting on a vendor patch."},
    {"when": "Week 5", "label": "General launch", "status": "planned"},
  ],
)
```

```ui
t2 = timeline(
  title: "Quarter at a glance",
  orientation: "horizontal",
  item: [
    {"when": "Jan", "label": "Kickoff", "status": "done"},
    {"when": "Feb", "label": "Prototype", "status": "done"},
    {"when": "Mar", "label": "Alpha", "status": "active", "owner": "Core"},
    {"when": "Apr", "label": "Beta", "status": "planned"},
    {"when": "May", "label": "Security review", "status": "blocked", "note": "Needs an external audit slot."},
    {"when": "Jun", "label": "Launch", "status": "planned"},
    {"when": "Jul", "label": "Retrospective", "status": "planned"},
    {"when": "Aug", "label": "Handover", "status": "planned"},
  ],
)
```

```ui
t3 = timeline(
  item: [
    {"when": "Now", "label": "Only one milestone", "status": "planned"},
  ],
)
```
