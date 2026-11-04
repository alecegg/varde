# Widget matrix: rich screen flow

Two lanes of wireframe screens: a web checkout and a mobile receipt, joined by labelled steps.

```ui
f1 = screen-flow(
  title: "Checkout across devices",
  desc: "The buyer pays on the web and later reads the receipt on a phone.",
  lanes: [
    {"title": "Web", "screens": ["cart", "pay", "done"]},
    {"title": "Phone", "screens": ["inbox", "receipt"]},
  ],
  screens: [
    {"id": "cart", "title": "Cart", "surface": "browser",
     "grid": ["HHHH", "LLLS", "LLLS", "BBBB"],
     "regions": {"H": "header", "L": "lines", "S": "summary", "B": "pay button"},
     "kinds": {"H": "nav", "L": "list", "S": "text", "B": "action"},
     "notes": [{"region": "B", "text": "Disabled while the cart is empty"},
               {"region": "L", "text": "Quantity changes save at once"}]},
    {"id": "pay", "title": "Payment", "surface": "browser",
     "grid": ["HHH", "FFF", "BBB"],
     "regions": {"H": "header", "F": "card form", "B": "confirm"},
     "kinds": {"F": "input", "B": "action"},
     "notes": [{"region": "F", "text": "Card number is never stored"}]},
    {"id": "done", "title": "Thanks", "surface": "browser",
     "grid": ["HH", "MM"], "regions": {"H": "header", "M": "confirmation"},
     "kinds": {"M": "media"}},
    {"id": "inbox", "title": "Inbox", "surface": "phone",
     "grid": ["HH", "LL", "LL"], "regions": {"H": "title", "L": "messages"},
     "kinds": {"L": "list"}},
    {"id": "receipt", "title": "Receipt", "surface": "phone",
     "grid": ["HH", "RR", "AA"], "regions": {"H": "title", "R": "receipt", "A": "share"},
     "kinds": {"A": "action"},
     "notes": [{"region": "A", "text": "Opens the share sheet"}]},
  ],
  steps: [
    {"from": "cart", "to": "pay", "label": "Pay"},
    {"from": "pay", "to": "done", "label": "Card accepted"},
    {"from": "inbox", "to": "receipt", "label": "Open"},
  ],
)
```

```ui
f2 = screen-flow(
  desc: "One screen with no steps.",
  screens: [
    {"id": "only", "title": "Only", "grid": ["AB"], "regions": {"A": "a", "B": "b"}},
  ],
)
```
