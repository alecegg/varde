# Middleware or route handlers

Two ways to place session validation.

## Options

```ui
opts = table(caption: "Options", columns: ["option", "where it runs"], rows: [["Middleware", "before every route"], ["Route handlers", "inside each route"]])
```

## Tradeoffs

```ui
tradeoffs = table(caption: "Tradeoffs", columns: ["option", "pro", "con"], rows: [["Middleware", "one place", "runs on public routes"], ["Route handlers", "explicit", "easy to forget"]])
```

## Recommendation

```ui
rec = callout(tone: "decision", title: "Recommendation", text: "Use middleware and exempt the public routes.")
```
