# Lines of code by module

Code is the largest module.

```ui
lines = chart(kind: "bar", title: "Line counts", unit: "lines", labels: ["core", "toz", "code", "workflow"], series: [{"name": "lines", "values": [12000, 8000, 21000, 15000]}])
```

```ui
tbl = table(caption: "Line counts", columns: ["module", "lines"], types: {"lines": "number"}, rows: [["core", 12000], ["toz", 8000], ["code", 21000], ["workflow", 15000]])
```
