# Widget matrix: rich annotated-code

A source file with numbered notes: gutter pins, folded quiet stretches and a margin column on a wide page.

```ui
a1 = annotated-code(
  filename: "queue.py",
  language: "python",
  source: "import json\nfrom pathlib import Path\n\nLIMIT = 0x1F  # the largest batch\n\n\ndef load(path: str) -> dict:\n    \"\"\"Read the queue file and return its items.\"\"\"\n    text = Path(path).read_text()\n    if not text:\n        return {\"items\": [], \"limit\": LIMIT}\n    return json.loads(text)\n\n\ndef helper_1(x):\n    return x + 1\n\n\ndef helper_2(x):\n    return x + 2\n\n\ndef helper_3(x):\n    return x + 3\n\n\ndef helper_4(x):\n    return x + 4\n\n\ndef helper_5(x):\n    return x + 5\n\n\ndef helper_6(x):\n    return x + 6\n\n\ndef helper_7(x):\n    return x + 7\n\n\ndef helper_8(x):\n    return x + 8\n\n\ndef save(path: str, items: list) -> None:\n    Path(path).write_text(json.dumps({\"items\": items}))\n",
  notes: [{"lines": "4", "label": "Limit", "note": "The batch limit is `0x1F`; raise it with care.", "kind": "warn"}, {"lines": "7-9", "label": "Load", "note": "Reads the whole file at once.", "kind": "info"}, {"lines": "11", "note": "An empty file yields no items.", "kind": "change"}, {"lines": 33, "note": "Writes without a lock.", "kind": "warn"}],
)
```
```ui
a2 = annotated-code(
  filename: "tiny.sh",
  language: "shell",
  source: "echo one\necho two\necho three\n",
  collapse: false,
  notes: [{"lines": "2-3", "note": "Both lines print."}],
)
```
```ui
a3 = annotated-code(
  filename: "plain.txt",
  language: "text",
  source: "no notes here\nso a plain panel\n",
  notes: [],
)
```

Plain prose after the components.
