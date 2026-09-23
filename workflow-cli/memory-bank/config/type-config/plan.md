---
allowed_transitions:
  backlog:
    - active
    - archived
  active:
    - blocked
    - completed
    - archived
  blocked:
    - active
    - archived
terminal_statuses:
  - completed
  - archived
child_type: task
fields:
  status:
    type: enum
    values:
      - backlog
      - active
      - blocked
      - completed
      - archived
    required: true
anomaly_check:
  mode: advisory
---
