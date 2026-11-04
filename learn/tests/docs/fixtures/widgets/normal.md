# Widget matrix: normal

Intro paragraph with `inline code` and a [link](https://example.com/page).

## Section

- first item
- second item
  - nested item

1. one
2. two

```python
print('hello')
```

| name | value |
| --- | --- |
| a | 1 |
| b | 2 |

```ui
w-choice = choice(question: "Which rollout?", options: ["Canary first", {"label": "Everyone at once", "detail": "Fast, no rollback window.", "recommended": true}, "Hold"], comment: true)
```

```ui
w-form = form(title: "Release details", fields: [{"name": "owner", "label": "Owner", "type": "text", "required": true}, {"name": "count", "label": "Hosts", "type": "number", "min": 1, "max": 99}, {"name": "env", "label": "Environment", "type": "select", "options": ["staging", "prod"]}, {"name": "notify", "label": "Notify the team", "type": "checkbox"}], submit: "Save")
```

```ui
w-ranking = ranking(question: "Order the risks", items: ["Data loss", "Downtime", {"label": "Cost", "detail": "Monthly spend."}, "Latency"])
```

```ui
w-slider = slider(label: "Confidence", min: 0, max: 10, step: 1, labels: ["Low", "High"])
```

```ui
w-decision = decision(question: "Ship it?", options: ["approve", "deny", "comment"], evidence: [{"label": "tests", "text": "all green"}, {"label": "review", "text": "two rounds"}], diff: "- old line\n+ new line")
```

```ui
w-comment = comment(label: "Anything else?", submit: "Send")
```

```ui
inc = include(source: "include-source.md", select: "acceptance")
```

```ui
inc2 = include(source: "include-source.md", select: "heading:my-notes")
```
