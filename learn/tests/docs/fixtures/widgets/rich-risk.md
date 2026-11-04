# Widget matrix: rich risks

Launch risks placed by likelihood and impact.

```ui
k1 = risks(
  title: "Launch risks",
  item: [
    {"id": "R1", "label": "Vendor patch slips", "likelihood": "high", "impact": "high", "mitigation": "Ship behind a feature flag.", "owner": "Platform"},
    {"id": "R2", "label": "Docs lag the release", "likelihood": "medium", "impact": "low", "mitigation": "Draft docs before code freeze."},
    {"id": "R3", "label": "Pilot team churn", "likelihood": "low", "impact": "high", "owner": "People"},
    {"id": "R4", "label": "Load test misses peak", "likelihood": "medium", "impact": "high", "mitigation": "Replay last quarter's traffic at 2x."},
    {"id": "R5", "label": "Licence audit", "likelihood": "low", "impact": "low"},
    {"id": "R6", "label": "Data migration drift", "likelihood": "high", "impact": "medium", "mitigation": "Run a dry migration weekly."},
    {"id": "R7", "label": "On-call gap in week 5", "likelihood": "medium", "impact": "medium"},
  ],
)
```

```ui
k2 = risks(
  title: "One risk",
  item: [
    {"id": "R1", "label": "Only risk", "likelihood": "low", "impact": "medium"},
  ],
)
```

```ui
k3 = risks(
  title: "Crowded cell",
  item: [
    {"id": "C1", "label": "Crowded risk 1", "likelihood": "high", "impact": "high"},
    {"id": "C2", "label": "Crowded risk 2", "likelihood": "high", "impact": "high"},
    {"id": "C3", "label": "Crowded risk 3", "likelihood": "high", "impact": "high"},
    {"id": "C4", "label": "Crowded risk 4", "likelihood": "high", "impact": "high"},
    {"id": "C5", "label": "Crowded risk 5", "likelihood": "high", "impact": "high"},
    {"id": "C6", "label": "Crowded risk 6", "likelihood": "high", "impact": "high"},
    {"id": "C7", "label": "Crowded risk 7", "likelihood": "high", "impact": "high"},
  ],
)
```

