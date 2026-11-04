# Widget matrix: rich diff

Before and after text diffs: unified and split, folded unchanged runs, notes, a patch input, added and removed files.

```ui
d1 = diff(
  filename: "queue.py",
  language: "python",
  before: "def f1(x):\n    return x + 1\n\ndef f2(x):\n    return x + 2\n\ndef f3(x):\n    return x + 3\n\ndef f4(x):\n    return x + 4\n\ndef f5(x):\n    return x + 5\n\ndef f6(x):\n    return x + 6\n\ndef f7(x):\n    return x + 7\n\ndef f8(x):\n    return x + 8\n\ndef f9(x):\n    return x + 9\n\ndef f10(x):\n    return x + 10\n\ndef f11(x):\n    return x + 11\n\ndef f12(x):\n    return x + 12\n\ndef f13(x):\n    return x + 13\n\ndef f14(x):\n    return x + 14\n\ndef f15(x):\n    return x + 15\n\n",
  after: "def f1(x):\n    return x + 1\n\ndef f2(x):\n    return x + 2\n\ndef f3(x):\n    return x * 3  # tripled\n\ndef f4(x):\n    return x + 4\n\ndef f5(x):\n    return x + 5\n\ndef f6(x):\n    return x + 6\n\ndef f7(x):\n    return x + 7\n\ndef f8(x):\n    return x + 8\n\ndef f9(x, y=0):\n    return x + 9\n\ndef f10(x):\n    return x + 10\n\ndef f11(x):\n    return x + 11\n\ndef f12(x):\n    return x + 12\n\ndef f13(x):\n    return x + 13\n\ndef f14(x):\n    return x + 14\n\ndef f15(x):\n    return x + 15\n\ndef extra():\n    return None\n",
  mode: "split",
  notes: [{"side": "after", "lines": "8-9", "note": "Triple instead of add."}, {"side": "before", "lines": 8, "note": "The old line added three."}, {"side": "after", "lines": "26", "note": "A signature gained a default."}],
)
```
```ui
d2 = diff(
  filename: "queue.py",
  language: "python",
  before: "def f1(x):\n    return x + 1\n\ndef f2(x):\n    return x + 2\n\ndef f3(x):\n    return x + 3\n\ndef f4(x):\n    return x + 4\n\ndef f5(x):\n    return x + 5\n\ndef f6(x):\n    return x + 6\n\ndef f7(x):\n    return x + 7\n\ndef f8(x):\n    return x + 8\n\ndef f9(x):\n    return x + 9\n\ndef f10(x):\n    return x + 10\n\ndef f11(x):\n    return x + 11\n\ndef f12(x):\n    return x + 12\n\ndef f13(x):\n    return x + 13\n\ndef f14(x):\n    return x + 14\n\ndef f15(x):\n    return x + 15\n\n",
  after: "def f1(x):\n    return x + 1\n\ndef f2(x):\n    return x + 2\n\ndef f3(x):\n    return x * 3  # tripled\n\ndef f4(x):\n    return x + 4\n\ndef f5(x):\n    return x + 5\n\ndef f6(x):\n    return x + 6\n\ndef f7(x):\n    return x + 7\n\ndef f8(x):\n    return x + 8\n\ndef f9(x, y=0):\n    return x + 9\n\ndef f10(x):\n    return x + 10\n\ndef f11(x):\n    return x + 11\n\ndef f12(x):\n    return x + 12\n\ndef f13(x):\n    return x + 13\n\ndef f14(x):\n    return x + 14\n\ndef f15(x):\n    return x + 15\n\ndef extra():\n    return None\n",
  mode: "unified",
)
```
```ui
d3 = diff(
  patch: "--- a/queue.py\n+++ b/queue.py\n@@ -6,5 +6,5 @@\n \n def f3(x):\n-    return x + 3\n+    return x * 3  # tripled\n \n def f4(x):\n@@ -23,5 +23,5 @@\n     return x + 8\n \n-def f9(x):\n+def f9(x, y=0):\n     return x + 9\n \n@@ -44,2 +44,4 @@\n     return x + 15\n \n+def extra():\n+    return None",
  language: "python",
)
```
```ui
d4 = diff(
  filename: "new.sh",
  language: "shell",
  before: "",
  after: "echo one\necho two\n",
)
```
```ui
d5 = diff(
  filename: "gone.txt",
  before: "old one\nold two\n",
  after: "",
)
```
```ui
d6 = diff(
  filename: "same.txt",
  before: "a\nb\n",
  after: "a\nb\n",
)
```

Plain prose after the components.
