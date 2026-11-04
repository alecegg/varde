# Widget matrix: rich change

Change vocabulary on a data model and an endpoint: added, modified, removed and renamed.

```ui
m1 = data-model(
  entity: [
    {
      "name": "customer",
      "key": "id",
      "change": "modified",
      "was": "user",
      "fields": {
        "id": "uuid",
        "email": {"type": "text", "change": "added"},
        "full_name": {"type": "text", "change": "renamed", "was": "name"},
        "plan": {"type": "enum", "change": "modified", "was": "text"},
        "fax": {"type": "text", "change": "removed"},
      },
    },
    {"name": "legacy_order", "key": "id", "change": "removed", "fields": {"id": "uuid"}},
    {
      "name": "order",
      "key": "id",
      "fields": {"id": "uuid", "customer_id": "uuid", "total": "cents"},
      "relations": [{"to": "customer", "kind": "many-to-one"}],
    },
  ],
)
```

```ui
e1 = endpoint(
  method: "POST",
  path: "/v2/orders",
  auth: "bearer",
  summary: "Create an order",
  change: "renamed",
  was: "/orders",
  request: {
    "customer_id": "uuid",
    "total": {"type": "cents", "change": "modified", "was": "float"},
    "coupon": {"type": "text", "change": "added"},
    "note": {"type": "text", "change": "removed"},
  },
  responses: [
    {"status": 201, "body": "the new order", "change": "modified", "was": "the order id"},
    {"status": 422, "body": "validation errors"},
    {"status": 409, "body": "duplicate order", "change": "added"},
  ],
)
```

```ui
e2 = endpoint(
  method: "GET",
  path: "/orders",
  auth: "none",
  change: "removed",
  responses: [{"status": 200, "body": "all orders"}],
)
```
