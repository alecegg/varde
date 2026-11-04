# Typed blocks

Prose before stays byte for byte.  Trailing spaces here.  
A line with a tab:	and unicode: héllo 日本.

```data-model id=user-model
# the id field comes first
[[entity]]
name = "user"
key = "id"
fields = { id = "uuid", email = "text" }
```

Middle prose with `inline code` and a fenced example that must stay:

```toml
not = "a block"
```

```decision id=ship-it
question = "Ship it?"
options = ["approve", "deny", "comment"]
covers = ["user-model"]

[[evidence]]
label = "tests"
text = "all green"

[[evidence]]
label = "review"
text = "two rounds"
```

```deps id=task-graph
# order matters
a:
b: a
c: a, b
b: a, d
```

```recap id=change-recap
{"plan": "demo", "rows": [{"file": "a.py", "status": "modified", "hunk": "@@ -1 +1 @@", "tasks": ["t1"]}], "summary": {"modified": 1}}
```

- A list item with an indented block:

  ```flow id=steps
  title = "Two steps"

  [[step]]
  id = "a"
  text = "start"
  next = ["b"]

  [[step]]
  id = "b"
  text = "end"
  ```

Prose after, with no final newline.
