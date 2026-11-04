# Order cancellation logic

Can an order that is partly shipped be cancelled, and what happens to the shipped part?

```ui
st = state(title: "Order", desc: "An order is cancelled from open or from partly shipped.", states: [{"id": "open", "label": "Open", "kind": "initial"}, {"id": "part", "label": "Partly shipped"}, {"id": "cancelled", "label": "Cancelled", "kind": "final"}], transitions: [{"from": "open", "to": "part", "label": "ship some"}, {"from": "part", "to": "cancelled", "label": "cancel", "guard": "refund shipped part"}, {"from": "open", "to": "cancelled", "label": "cancel"}])
```

```ui
sc = table(caption: "Scenarios", columns: ["state", "action", "result"], rows: [["open", "cancel", "cancelled"], ["partly shipped", "cancel", "cancelled with refund"]])
```
