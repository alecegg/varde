# Widget matrix: rich er

The data-model graph layout: entity boxes, orthogonal relation lines with cardinality labels, an inferred relation, a self-relation, change markers, the relation list and the cards. The last model uses the default list layout.

```ui
g1 = data-model(
  layout: "graph",
  entity: [{"name": "customer", "key": "id", "fields": {"id": "uuid", "email": "text", "name": "text"}, "relations": [{"to": "address", "kind": "one-to-many"}]}, {"name": "address", "key": "id", "fields": {"id": "uuid", "line": "text", "city": "text"}}, {"name": "order", "key": "id", "fields": {"id": "uuid", "customer_id": "uuid", "total": {"type": "cents", "change": "modified", "was": "int"}, "coupon": {"type": "text", "change": "added"}}, "relations": [{"to": "customer", "kind": "many-to-one"}], "change": "modified"}, {"name": "order_line", "key": "id", "fields": {"id": "uuid", "order_id": "uuid", "product_id": "uuid", "qty": "int"}, "relations": [{"to": "order", "kind": "many-to-one"}]}, {"name": "product", "key": "id", "fields": {"id": "uuid", "sku": "text", "title": "text", "a": "t", "b": "t", "c": "t", "d": "t", "e": "t"}, "relations": [{"to": "product", "kind": "one-to-many"}]}, {"name": "tag", "key": "id", "fields": {"id": "uuid", "label": "text"}, "relations": [{"to": "product", "kind": "many-to-many"}, {"to": "customer", "kind": "one-to-one"}], "change": "added"}, {"name": "legacy", "key": "id", "fields": {"id": "uuid", "note": {"type": "text", "change": "removed"}}, "change": "removed"}],
)
```

```ui
l1 = data-model(
  entity: [{"name": "customer", "key": "id", "fields": {"id": "uuid"}}],
)
```
