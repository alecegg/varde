# Widget matrix: rich wireframe

A browser screen with kinds and pins, a phone before and after, and the screen states.

```ui
w1 = wireframe(
  title: "Orders list",
  surface: "browser",
  grid: ["HHHH", "SSLL", "SSLL", "FFFF"],
  regions: {"H": "header", "S": "filters", "L": "order list", "F": "footer"},
  kinds: {"H": "nav", "S": "input", "L": "list", "F": "text"},
  notes: [
    {"region": "S", "text": "Filters stay in the URL so a view can be shared"},
    {"region": "L", "text": "Rows load 50 at a time"},
    {"region": "L", "text": "A failed row shows Retry"},
  ],
)
```

```ui
w2 = wireframe(
  title: "Checkout",
  surface: "phone",
  grid: ["TTT", "MMM", "BBB"],
  regions: {"T": "title", "M": "order summary", "B": "pay button"},
  kinds: {"M": "media", "B": "action"},
  notes: [{"region": "B", "text": "Disabled until the card is valid"}],
  compare: {
    grid: ["TTT", "SSS", "MMM", "BBB"],
    regions: {"T": "title", "S": "saved cards", "M": "order summary", "B": "pay button"},
    kinds: {"S": "list", "M": "media", "B": "action"},
    notes: [{"region": "S", "text": "New: pick a saved card"}],
  },
)
```

```ui
s1 = ui-states(
  screen: "Orders list",
  empty: {"shows": "No orders yet, with a Create order button"},
  loading: {"shows": "Skeleton rows"},
  error: {"shows": "Message and a Retry button"},
)
```

```ui
s2 = ui-states(
  screen: "Order detail",
  layout: "grid",
  empty: {"na": "an order always has lines"},
  loading: {"shows": "Skeleton lines"},
  error: {"shows": "Message and a Retry button"},
)
```
