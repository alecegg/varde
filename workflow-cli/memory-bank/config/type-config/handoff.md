---
allowed_transitions:
  open:
    - resumed
    - archived
  resumed:
    - archived
terminal_statuses:
  - archived
fields:
  status:
    type: enum
    values:
      - open
      - resumed
      - archived
    required: true
---
