# Plan: retry queue

Failed jobs retry with a growing delay, and a stuck host stops blocking the others.

```ui
scope = callout(tone: "info", title: "Scope and non-goals", text: "In scope: retry delay, attempt count, one retry endpoint.\n\nNot in scope: a dead-letter queue or per-job retry settings.")
```

```ui
approach = diagram(kind: "graph", title: "Retry path", direction: "LR", nodes: [{"id": "fail", "label": "Job fails", "shape": "rounded"}, {"id": "wait", "label": "Wait 2^n s"}, {"id": "run", "label": "Run again"}, {"id": "park", "label": "Park job", "shape": "diamond"}], edges: [{"from": "fail", "to": "wait"}, {"from": "wait", "to": "run"}, {"from": "run", "to": "fail", "label": "fails", "style": "dashed"}, {"from": "run", "to": "park", "label": "5th fail"}])
```

```ui
files = file-tree(title: "File map", entries: [{"path": "src/queue.py", "change": "modified", "note": "calls schedule_retry"}, {"path": "src/retry.py", "change": "added"}, {"path": "tests/test_retry.py", "change": "added", "role": "test"}])
```

```ui
retry-code = annotated-code(filename: "retry.py", language: "python", source: "def schedule_retry(job):\n    delay = 2 ** job.attempts\n    queue.later(job, delay)\n", notes: [{"lines": 2, "label": "Backoff", "note": "The delay doubles on each attempt.", "kind": "info"}])
```

```ui
criteria = checklist(title: "Acceptance criteria", items: [{"label": "A failed job retries after 2^n seconds"}, {"label": "The fifth failure parks the job"}, {"label": "Jobs keep their order"}])
```

```ui
risk = callout(tone: "risk", title: "Retry storms", text: "Jobs that fail together retry together. A jitter spreads the retries.")
```

```ui
questions = form(title: "Open questions", submit: "Send answers", fields: [{"name": "cap", "label": "Retries before parking", "type": "number", "min": 1, "max": 20}, {"name": "jitter", "label": "Add jitter", "type": "checkbox"}])
```
