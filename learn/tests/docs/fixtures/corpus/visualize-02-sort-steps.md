# Bubble sort on [5, 2, 9, 1, 7]

Each pass as a table; live animation is not offered in a page.

```ui
passes = table(caption: "Passes", columns: ["pass", "array", "swaps"], rows: [[1, "2 5 1 7 9", 3], [2, "2 1 5 7 9", 1], [3, "1 2 5 7 9", 1], [4, "1 2 5 7 9", 0]])
```

```ui
steps = flow(title: "One pass", step: [{"id": "cmp", "text": "Compare neighbours", "next": ["swap", "skip"]}, {"id": "swap", "text": "Swap if out of order", "next": ["cmp"]}, {"id": "skip", "text": "Move on"}])
```
