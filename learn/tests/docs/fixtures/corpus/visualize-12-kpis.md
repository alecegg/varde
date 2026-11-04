# Three KPIs

Three KPIs for the quarter.

```ui
k1 = chart(kind: "bar", title: "Active users", unit: "k", labels: ["Q3"], series: [{"name": "users", "values": [48]}])
```

```ui
k2 = chart(kind: "bar", title: "Conversion", unit: "%", labels: ["Q3"], series: [{"name": "rate", "values": [3.4]}])
```

```ui
k3 = table(caption: "Revenue", columns: ["metric", "value"], rows: [["MRR", "151k"]])
```
