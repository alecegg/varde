# Widget matrix: rich callout

The five tones, as the callout component draws them.

```ui
c1 = callout(
  tone: "info",
  title: "Context",
  text: "The export keeps the `data-copy` text and prints every note.",
)
```

```ui
c2 = callout(
  tone: "decision",
  title: "Storage",
  text: "Use SQLite for the `queue` table.\n\nOne writer is enough for this load.",
)
```

```ui
c3 = callout(
  tone: "risk",
  text: "A slow migration can block writes for several minutes.",
)
```

```ui
c4 = callout(
  tone: "warning",
  title: "Rollout",
  text: "Run the migration before the deploy, not after.",
)
```

```ui
c5 = callout(
  tone: "success",
  title: "Done",
  text: "All 12 checks pass on the three supported platforms.",
)
```
