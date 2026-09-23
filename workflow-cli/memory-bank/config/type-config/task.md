---
allowed_transitions:
  draft:
    - ready
    - blocked
  ready:
    - in_progress
    - blocked
  in_progress:
    - done
    - blocked
  done:
    - blocked
  blocked:
    - ready
terminal_statuses:
  - done
append_log:
  path: '{planDir}/log.md'
  template: '**Update** {timestamp} — task: {id} from: {from} to: {to} reason: {reason}'
content_hash_gate:
  source_field: acceptance_criteria
  derived_field: ac_score_hash
dependency_gate:
  list_field: depends_on
  satisfied_when_status: done
rollback_on_failure: true
fields:
  status:
    type: enum
    values:
      - draft
      - ready
      - in_progress
      - done
      - blocked
    required: true
  depends_on:
    type: array
  acceptance_criteria:
    type: array
  ac_score_hash:
    type: string
  ac_scores:
    type: array
anomaly_check:
  mode: advisory
---
