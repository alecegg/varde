# Recap: retry queue

Failed jobs now retry with a growing delay, so one bad host no longer stalls the queue.

```ui
wf-before = wireframe(title: "Jobs page before", grid: ["HHHH", "LLLL", "LLLL"], regions: {"H": "header", "L": "job list"}, kinds: {"H": "nav", "L": "list"})
wf-after = wireframe(title: "Jobs page after", grid: ["HHHH", "LLLR", "LLLR"], regions: {"H": "header", "L": "job list", "R": "retry panel"}, kinds: {"H": "nav", "L": "list", "R": "action"}, notes: [{"region": "R", "text": "Shows the next retry time"}])
ui-change = columns(col: [{"label": "Before", "blocks": ["wf-before"]}, {"label": "After", "blocks": ["wf-after"]}])
```

```ui
schema = data-model(entity: [{"name": "job", "key": "id", "fields": {"id": "uuid", "attempts": {"type": "int", "change": "added"}, "state": "text"}}])
```

```ui
api = endpoint(method: "POST", path: "/jobs/{id}/retry", auth: "bearer", summary: "Retry a failed job now", responses: [{"status": 202, "body": "retry queued", "change": "added"}, {"status": 409, "body": "job is not failed", "change": "added"}], change: "added")
```

```ui
files = file-tree(title: "Changed files", entries: [{"path": "src/queue.py", "change": "modified", "note": "push returns the id"}, {"path": "src/retry.py", "change": "added"}, {"path": "tests/test_retry.py", "change": "added", "role": "test"}])
```

```ui
retry-diff = diff(filename: "queue.py", language: "python", before: "def fail(job):\n    job.state = 'failed'\n", after: "def fail(job):\n    job.state = 'failed'\n    schedule_retry(job)\n", notes: [{"side": "after", "lines": "3", "note": "Retry is queued here."}])
retry-code = annotated-code(filename: "retry.py", language: "python", source: "def schedule_retry(job):\n    delay = 2 ** job.attempts\n    queue.later(job, delay)\n", notes: [{"lines": 2, "label": "Backoff", "note": "The delay doubles on each attempt.", "kind": "info"}])
key-changes = tabs(tab: [{"label": "Diff", "blocks": ["retry-diff"]}, {"label": "Annotated", "blocks": ["retry-code"]}])
```

```ui
checks = checklist(title: "Verification", items: [{"label": "Retry delay doubles", "status": "done"}, {"label": "Failed jobs keep their order", "status": "done"}, {"label": "Load test on staging", "status": "open"}])
```

```ui
numbers = stats(item: [{"label": "Stuck jobs", "value": 3, "delta": "-12", "good": "down", "direction": "down"}, {"label": "Retries per hour", "value": 240}])
```

```ui
options = matrix(title: "Retry policy", options: [{"id": "fixed", "label": "Fixed delay"}, {"id": "backoff", "label": "Backoff"}], criteria: [{"id": "load", "label": "Gentle on a failing host", "weight": 3}, {"id": "simple", "label": "Simple to explain"}], cells: [["no", "yes"], ["yes", "partial"]], recommended: "backoff")
```

```ui
risk = callout(tone: "risk", title: "Retry storms", text: "Many jobs failing together retry together. The delay has a jitter to spread them.")
```

```ui
settled = callout(tone: "decision", title: "Storage", text: "Attempt counts live in the `job` table; no new store.")
```

```ui
open = choice(question: "Cap the retries?", options: [{"label": "Five attempts", "detail": "Then park the job.", "recommended": true}, {"label": "No cap", "detail": "Retry until fixed."}], comment: true)
```
