# Widget matrix: rich state

A job lifecycle with an initial, final and error state, a guard, a self-loop and a loop-back.

```ui
s1 = state(
  title: "Job lifecycle",
  desc: "A job waits, runs, and ends done or failed; failed jobs retry up to three times.",
  states: [
    {"id": "idle", "label": "Idle", "kind": "initial", "note": "Waiting in the queue."},
    {"id": "run", "label": "Running"},
    {"id": "wait", "label": "Waiting for a worker"},
    {"id": "done", "label": "Done", "kind": "final"},
    {"id": "bad", "label": "Failed", "kind": "error"},
    {"id": "orphan", "label": "Orphaned"},
  ],
  transitions: [
    {"from": "idle", "to": "wait", "label": "enqueue"},
    {"from": "wait", "to": "run", "label": "start"},
    {"from": "run", "to": "done", "label": "finish"},
    {"from": "run", "to": "bad", "label": "crash"},
    {"from": "bad", "to": "run", "label": "retry", "guard": "attempts < 3"},
    {"from": "run", "to": "run", "label": "heartbeat"},
    {"from": "run", "to": "run", "label": "checkpoint"},
    {"from": "orphan", "to": "idle", "label": "adopt"},
  ],
)
```

```ui
s2 = state(
  desc: "One state with no transitions.",
  states: [{"id": "only", "label": "Only", "kind": "initial"}],
)
```
