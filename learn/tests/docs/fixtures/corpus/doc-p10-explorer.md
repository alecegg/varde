# Reference size explorer

Move the slider to see how the p10 standard deviation and the product confidence change with the reference size n.

```ui
n = slider(label: "Reference size n", min: 0, max: 5, step: 1, labels: ["5", "200"])
```

```ui
sd = chart(kind: "bar", title: "p10 sd by reference size", unit: "points", labels: ["5", "10", "20", "50", "100", "200"], series: [{"name": "sd", "values": [15.1, 23.0, 11.9, 6.6, 3.6, 2.3]}])
```

```ui
conf = table(caption: "Product confidence", columns: ["n", "confidence"], rows: [["below 20", "insufficient (no verdict)"], ["20 to 49", "low confidence"], ["50 and up", "ok"]])
```
