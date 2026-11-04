# Widget matrix: rich flow

A checkout and a deploy, as the flow component draws them.

```ui
f1 = flow(
  title: "Checkout",
  step: [
    {"id": "cart", "text": "Review cart", "next": ["pay"]},
    {"id": "pay", "text": "Pay with a saved card or a new one", "next": ["done", "failed"]},
    {"id": "done", "text": "Show receipt"},
    {"id": "failed", "text": "Show error and offer another card", "next": ["pay"]},
  ],
)
```

```ui
f2 = flow(
  title: "Deploy",
  step: [
    {"id": "build", "text": "Build", "next": ["test", "lint"]},
    {"id": "test", "text": "Run tests", "next": ["ship"]},
    {"id": "lint", "text": "Lint", "next": ["ship"]},
    {"id": "ship", "text": "Ship to staging", "next": ["verify"]},
    {"id": "verify", "text": "Verify"},
  ],
)
```
