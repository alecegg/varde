# Widget matrix: rich wireframe stress

Hostile prose: <script>alert(1)</script> and bidi ‮evil‬ text.

```ui
w1 = wireframe(
  title: "<script>alert(1)</script> Wide screen with long labels",
  surface: "browser",
  grid: ["ABCDEFGHIJKL", "ABCDEFGHIJKL", "MMMMNNNNOOOO", "PPPPPPPPPPPP"],
  regions: {
    "A": "<img src=x onerror=1> a label that is much too long for a narrow cell",
    "B": "שלום עולם, זו תווית ארוכה בעברית",
    "C": "مرحبا بالعالم هذا نص عربي طويل",
    "D": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "E": "e", "F": "f", "G": "g", "H": "h", "I": "i", "J": "j", "K": "k", "L": "l",
    "M": "media", "N": "named", "O": "other", "P": "footer with a long text that wraps over several lines in a wide cell",
  },
  kinds: {"A": "nav", "B": "text", "C": "media", "D": "input", "E": "action", "F": "list", "M": "media", "P": "text"},
  notes: [
    {"region": "A", "text": "<b>Bold</b> \"quoted\" & ampersand " },
    {"region": "A", "text": "Second note on the same region"},
    {"region": "A", "text": "Third note on the same region"},
    {"region": "D", "text": "A very long note xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    {"region": "P", "text": "שלום עולם"},
  ],
)
```

```ui
w2 = wireframe(
  title: "Tablet before and after",
  surface: "tablet",
  grid: ["AAAAAAAA", "BBCCCCCC", "BBCCCCCC"],
  regions: {"A": "header", "B": "side", "C": "main"},
  compare: {
    grid: ["AAAAAAAA", "CCCCCCCC", "CCCCCCCC"],
    regions: {"A": "header", "C": "main"},
    notes: [{"region": "C", "text": "The side panel moved into the header menu"}],
  },
)
```

```ui
s1 = ui-states(
  screen: "<script>alert(1)</script>",
  empty: {"shows": "No orders <b>yet</b>"},
  loading: {"shows": "Skeleton rows"},
  error: {"na": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
  offline: {"shows": "Banner: you are offline"},
  partial: {"shows": "Some rows failed to load"},
)
```
