# Last quarter

Signups grew, churn held and revenue rose.

## Signups

```ui
signups = chart(kind: "line", title: "Signups", labels: ["Jul", "Aug", "Sep"], series: [{"name": "signups", "values": [320, 410, 455]}])
```

## Churn

```ui
churn = chart(kind: "line", title: "Churn", unit: "%", labels: ["Jul", "Aug", "Sep"], series: [{"name": "churn", "values": [2.1, 1.8, 1.9]}])
```

## Revenue

```ui
revenue = chart(kind: "bar", title: "Revenue", unit: "k", labels: ["Jul", "Aug", "Sep"], series: [{"name": "revenue", "values": [120, 138, 151]}])
```
