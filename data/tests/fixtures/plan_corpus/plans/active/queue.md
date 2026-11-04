# Anonymized plan queue

A copied table queue with anonymized rows for codec round-trip coverage.

| id | plan dir | findings | owned files | depends_on / serialize-with | priority | state | planned_at | plan_reviewed_at | build_started_at | build_done_at | merged_at |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | example-plan-one | Example finding one | `example/src/one.py`, `example/tests/test_one.py` | none | 1 | merged | 2026-10-01T10:00Z | 2026-10-01T11:00Z | 2026-10-01T12:00Z | 2026-10-01T13:00Z | 2026-10-01T14:00Z |
| B | example-plan-two | Example finding two | `example/src/two.py` | plan depends_on A | 2 | queued | 2026-10-01T10:00Z |  |  |  |  |
<!-- Anonymized trailing queue note. -->
