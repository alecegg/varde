# Migrated page

Intro text.

```decision id=pick
question = "Ship it?"
options = ["approve", "deny", "comment"]
```

## Options

```table id=opts
columns = ["option", "cost"]
rows = [["queue", "30"], ["cache", "5"]]
```

```deps id=graph
a:
b: a
```

```recap id=rc
{"rows": [{"file": "a.py", "status": "modified", "hunk": "@@ -1 +1 @@"}]}
```
