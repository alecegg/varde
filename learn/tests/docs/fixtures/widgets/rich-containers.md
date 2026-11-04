# Widget matrix: rich containers

Tabs and columns that hold other blocks of the page by id.

```ui
code1 = code(
  language: "python",
  title: "queue.py",
  source: "def push(item):\n    queue.append(item)\n",
)
```

```ui
diff1 = diff(
  filename: "queue.py",
  language: "python",
  before: "def push(item):\n    queue.append(item)\n",
  after: "def push(item):\n    if not item:\n        return\n    queue.append(item)\n",
  mode: "unified",
)
```

```ui
tree1 = file-tree(
  title: "Changed files",
  entries: [
    {"path": "src/queue.py", "change": "modified"},
    {"path": "tests/test_queue.py", "change": "added", "role": "test"},
  ],
)
```

```ui
list1 = checklist(
  title: "Checks",
  items: [{"label": "Queue keeps order", "status": "done"}, {"label": "Docs updated"}],
)
```

```ui
note1 = callout(
  tone: "info",
  title: "Context",
  text: "The held blocks keep their own menus.",
)
```

```ui
tabs1 = tabs(
  tab: [
    {"label": "Code", "blocks": ["code1"]},
    {"label": "Change", "blocks": ["diff1", "tree1"]},
    {"label": "Checks", "blocks": ["list1"]},
  ],
)
```

Between the containers: ordinary prose stays at the top level.

```ui
c2 = code(
  language: "js",
  title: "fetch.js",
  source: "const retries = 3;\n",
)
```

```ui
cols1 = columns(
  col: [
    {"label": "Context", "blocks": ["note1"]},
    {"label": "Code", "blocks": ["c2"]},
  ],
)
```
