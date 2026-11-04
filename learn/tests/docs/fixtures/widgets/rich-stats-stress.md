# Widget matrix: rich stats stress

Hostile prose: <script>alert(1)</script> and bidi ‮evil‬ text.

```ui
h1 = stats(
  item: [
    {"label": "<script>alert(1)</script> \"><img src=x onerror=1>", "value": "<b>1</b>", "delta": "+<i>9</i>%", "direction": "up", "good": "down", "note": "<b>note</b> `<i>c</i>`"},
    {"label": "שלום עולם, תווית ארוכה", "value": "١٢٣٤٥ مرحبا بالعالم", "delta": "-3%", "good": "up"},
    {"label": "Forty character value case", "value": "1,234,567 requests per second sustained now", "delta": "12,345,678 more than last week at peak", "direction": "up", "good": "up"},
    {"label": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "value": "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy", "delta": "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "direction": "down", "note": "nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn"},
    {"label": "bidi ‮evil‬ label word word word word word word word word word word word word word word word word word word ", "value": "v v v v v v v v v v v v v v v v v v v v v v v v v v v v v v ", "delta": "word word word word word word word word word word word word word word word word word word ", "direction": "flat", "note": "word word word word word word word word word word word word word word word word word word "},
    {"label": "Tone override", "value": 0, "decimals": 3, "tone": "decision", "delta": 0},
  ],
)
```

```ui
h2 = stats(
  item: [
    {"label": "A", "value": 1},
    {"label": "B", "value": "40 characters of value text here ok."},
  ],
)
```
