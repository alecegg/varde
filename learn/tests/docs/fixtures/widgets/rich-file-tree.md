# Widget matrix: rich file-tree

Changed files as a folder tree: markers, a rename, notes, roles, a collapsed level and a link to a code block.

```ui
ft1 = file-tree(
  title: "Changed files",
  entries: [
    {"path": "src/queue.py", "change": "modified", "note": "push returns the id"},
    {"path": "src/retry.py", "change": "added", "note": "backoff helper"},
    {"path": "src/backoff.py", "change": "renamed", "was": "src/wait.py"},
    {"path": "src/old_limit.py", "change": "removed"},
    {"path": "src/util/text/slug.py"},
    {"path": "tests/test_queue.py", "change": "modified", "role": "test"},
    {"path": "README.md"},
  ],
)
```

```ui
ft2 = file-tree(
  title: "Collapsed below the first level",
  collapse: 1,
  entries: [
    {"path": "app/core/models/order.py", "change": "added"},
    {"path": "app/core/models/item.py", "change": "added"},
    {"path": "app/core/views.py", "change": "modified"},
    {"path": "app/main.py"},
  ],
)
```

```ui
c1 = code(
  language: "python",
  title: "src/queue.py",
  source: "def push(item):\n    queue.append(item)\n    return len(queue)\n",
  mark: [3],
)
```
