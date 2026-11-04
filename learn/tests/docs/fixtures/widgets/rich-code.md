# Widget matrix: rich code

The code panel: highlighted listings, marked lines, a line range, wrapping, no numbers, and a plain fenced block.

```ui
c1 = code(
  language: "python",
  title: "queue.py",
  source: "import json\nfrom pathlib import Path\n\nLIMIT = 0x1F  # the largest batch\n\n\ndef load(path: str) -> dict:\n    \"\"\"Read the queue file and return its items.\"\"\"\n    text = Path(path).read_text()\n    if not text:\n        return {\"items\": [], \"limit\": LIMIT, \"ok\": True}\n    return json.loads(text)\n",
  mark: [5, [10, 11]],
)
```
```ui
c2 = code(
  language: "js",
  title: "fetch.js",
  source: "const retries = 3;\n\n// wait before the next attempt\nasync function fetchItems(url, delay = 250) {\n  for (let i = 0; i < retries; i++) {\n    const res = await fetch(`${url}?page=${i}`);\n    if (res.ok) return res.json();\n  }\n  return null;\n}\n",
  lines: [3, 9],
  wrap: true,
)
```
```ui
c3 = code(
  language: "shell",
  source: "#!/bin/sh\n# build then test\nfor pkg in core learn; do\n  uv run pytest \"$pkg/tests\" -q || exit 1\ndone\necho 'done'\n",
  numbers: false,
)
```
```ui
c4 = code(
  language: "json",
  title: "queue.json",
  source: "{\n  \"name\": \"queue\",\n  \"workers\": 4,\n  \"debug\": false,\n  \"tags\": [\"a\", \"b\"]\n}\n",
  mark: [[2, 3]],
)
```
A plain fenced block:

```py
print('hello')  # not a component
```
