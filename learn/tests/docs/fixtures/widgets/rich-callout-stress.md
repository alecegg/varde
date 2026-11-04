# Widget matrix: rich callout stress

Hostile prose: <script>alert(1)</script> and bidi ‮evil‬ text.

```ui
h1 = callout(
  tone: "info",
  title: "Title 1 <img src=x onerror=1> word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word",
  text: "<script>alert(1)</script> \\\"><img src=x onerror=1>",
)
```

```ui
h2 = callout(
  tone: "decision",
  title: "Title 2 <img src=x onerror=1> word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word",
  text: "שלום עולם, זו תווית ארוכה בעברית",
)
```

```ui
h3 = callout(
  tone: "risk",
  title: "Title 3 <img src=x onerror=1> word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word",
  text: "مرحبا بالعالم هذا نص عربي طويل",
)
```

```ui
h4 = callout(
  tone: "warning",
  title: "Title 4 <img src=x onerror=1> word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word",
  text: "Unbroken xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
)
```

```ui
h5 = callout(
  tone: "success",
  title: "Title 5 <img src=x onerror=1> word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word",
  text: "bidi ‮evil‬ text and `<b>code</b>` span",
)
```

```ui
long = callout(
  tone: "warning",
  text: "word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\nword word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word\n\n",
)
```

```ui
m0 = callout(
  tone: "info",
  title: "Item 0",
  text: "Note 0 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m1 = callout(
  tone: "decision",
  title: "Item 1",
  text: "Note 1 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m2 = callout(
  tone: "risk",
  title: "Item 2",
  text: "Note 2 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m3 = callout(
  tone: "warning",
  title: "Item 3",
  text: "Note 3 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m4 = callout(
  tone: "success",
  title: "Item 4",
  text: "Note 4 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m5 = callout(
  tone: "info",
  title: "Item 5",
  text: "Note 5 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m6 = callout(
  tone: "decision",
  title: "Item 6",
  text: "Note 6 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m7 = callout(
  tone: "risk",
  title: "Item 7",
  text: "Note 7 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m8 = callout(
  tone: "warning",
  title: "Item 8",
  text: "Note 8 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m9 = callout(
  tone: "success",
  title: "Item 9",
  text: "Note 9 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m10 = callout(
  tone: "info",
  title: "Item 10",
  text: "Note 10 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m11 = callout(
  tone: "decision",
  title: "Item 11",
  text: "Note 11 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m12 = callout(
  tone: "risk",
  title: "Item 12",
  text: "Note 12 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m13 = callout(
  tone: "warning",
  title: "Item 13",
  text: "Note 13 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m14 = callout(
  tone: "success",
  title: "Item 14",
  text: "Note 14 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m15 = callout(
  tone: "info",
  title: "Item 15",
  text: "Note 15 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m16 = callout(
  tone: "decision",
  title: "Item 16",
  text: "Note 16 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m17 = callout(
  tone: "risk",
  title: "Item 17",
  text: "Note 17 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m18 = callout(
  tone: "warning",
  title: "Item 18",
  text: "Note 18 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m19 = callout(
  tone: "success",
  title: "Item 19",
  text: "Note 19 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m20 = callout(
  tone: "info",
  title: "Item 20",
  text: "Note 20 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m21 = callout(
  tone: "decision",
  title: "Item 21",
  text: "Note 21 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m22 = callout(
  tone: "risk",
  title: "Item 22",
  text: "Note 22 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m23 = callout(
  tone: "warning",
  title: "Item 23",
  text: "Note 23 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m24 = callout(
  tone: "success",
  title: "Item 24",
  text: "Note 24 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m25 = callout(
  tone: "info",
  title: "Item 25",
  text: "Note 25 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m26 = callout(
  tone: "decision",
  title: "Item 26",
  text: "Note 26 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m27 = callout(
  tone: "risk",
  title: "Item 27",
  text: "Note 27 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m28 = callout(
  tone: "warning",
  title: "Item 28",
  text: "Note 28 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m29 = callout(
  tone: "success",
  title: "Item 29",
  text: "Note 29 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m30 = callout(
  tone: "info",
  title: "Item 30",
  text: "Note 30 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m31 = callout(
  tone: "decision",
  title: "Item 31",
  text: "Note 31 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m32 = callout(
  tone: "risk",
  title: "Item 32",
  text: "Note 32 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m33 = callout(
  tone: "warning",
  title: "Item 33",
  text: "Note 33 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m34 = callout(
  tone: "success",
  title: "Item 34",
  text: "Note 34 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m35 = callout(
  tone: "info",
  title: "Item 35",
  text: "Note 35 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m36 = callout(
  tone: "decision",
  title: "Item 36",
  text: "Note 36 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m37 = callout(
  tone: "risk",
  title: "Item 37",
  text: "Note 37 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m38 = callout(
  tone: "warning",
  title: "Item 38",
  text: "Note 38 with `code` and a longer sentence that wraps on narrow screens.",
)
```

```ui
m39 = callout(
  tone: "success",
  title: "Item 39",
  text: "Note 39 with `code` and a longer sentence that wraps on narrow screens.",
)
```
