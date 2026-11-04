# Migrated page

Intro text.

```ui id=pick
pick = decision(question: "Ship it?", options: ["approve", "deny", "comment"])
```

## Options

```ui id=opts
opts = table(columns: ["option", "cost"], rows: [["queue", "30"], ["cache", "5"]])
```

```ui id=graph
graph = deps(edges: {"a": [], "b": ["a"]})
```

```ui id=rc
rc = recap(rows: [{"file": "a.py", "status": "modified", "hunk": "@@ -1 +1 @@"}])
```
