"""Block types for data and interfaces: data-model, endpoint."""

from varde_learn.docs.pages.blocks.change import CHANGE_FIELDS, change_faults
from varde_learn.docs.pages.blocks.er import LAYOUT_NOTE, layout_faults
from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec

_RELATION_KINDS = {"one-to-one", "one-to-many", "many-to-one", "many-to-many"}
_CHANGE_NOTE = (
    "Change (optional on an entity, field, endpoint, parameter or response):",
    *(f"  {line}" for line in CHANGE_FIELDS),
)
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def _relation_faults(
    relation: dict[str, object], names: set[str], where: str
) -> list[Fault]:
    faults = check_keys(relation, {"to", "kind"}, set(), where)
    faults += str_field(relation, "to", where)
    target = relation.get("to")
    if isinstance(target, str) and target not in names:
        faults.append(
            Fault(
                "relation-target",
                f"{where}: relation target '{target}' is not an entity",
            )
        )
    kind = relation.get("kind")
    if kind is not None and kind not in _RELATION_KINDS:
        faults.append(
            Fault("type", f"{where}: kind must be one of {sorted(_RELATION_KINDS)}")
        )
    return faults


def _typed_map_faults(value: object, where: str) -> list[Fault]:
    """A table of `name: type text` or `name: {type, change, was}`."""
    if not isinstance(value, dict) or not value:
        return [Fault("type", f"{where} must be a non-empty table of strings")]
    faults: list[Fault] = []
    for name, item in value.items():
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            faults.append(Fault("type", f"{where}.{name} must be a string or a table"))
            continue
        item_where = f"{where}.{name}"
        faults += check_keys(item, {"type"}, {"change", "was"}, item_where)
        faults += str_field(item, "type", item_where)
        faults += change_faults(item, item_where)
    return faults


def _entity_faults(
    entity: dict[str, object], names: set[str], where: str
) -> list[Fault]:
    faults = check_keys(
        entity, {"name", "key", "fields"}, {"relations", "change", "was"}, where
    )
    faults += str_field(entity, "name", where) + str_field(entity, "key", where)
    faults += change_faults(entity, where)
    fields = entity.get("fields")
    if "fields" in entity:
        faults += _typed_map_faults(fields, f"{where}.fields")
    key = entity.get("key")
    if isinstance(key, str) and isinstance(fields, dict) and key not in fields:
        faults.append(
            Fault("entity-key", f"{where}: key '{key}' is not a declared field")
        )
    faults += tables_fault(entity, "relations", where)
    for n, relation in enumerate(tables(entity, "relations", where), 1):
        faults += _relation_faults(relation, names, f"{where}.relations[{n}]")
    return faults


def validate_data_model(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"entity"}, {"layout"}, "data-model")
    faults += layout_faults(data)
    faults += tables_fault(data, "entity", "data-model")
    entities = tables(data, "entity", "data-model")
    named = [n for e in entities if isinstance(n := e.get("name"), str)]
    faults += [
        Fault("entity-duplicate", f"entity '{name}' is declared more than once")
        for name in duplicates(named)
    ]
    for n, entity in enumerate(entities, 1):
        faults += _entity_faults(entity, set(named), f"entity[{n}]")
    return faults


def validate_endpoint(data: dict[str, object]) -> list[Fault]:
    required = {"method", "path", "auth", "responses"}
    optional = {"summary", "request", "change", "was"}
    faults = check_keys(data, required, optional, "endpoint")
    faults += change_faults(data, "endpoint")
    if "auth" not in data:
        faults = [f for f in faults if "'auth'" not in f.message]
        faults.append(
            Fault(
                "endpoint-auth",
                'endpoint: auth is required; write auth = "none" if it is public',
            )
        )
    faults += str_field(data, "auth", "endpoint") + str_field(
        data, "summary", "endpoint"
    )
    method = data.get("method")
    if "method" in data and method not in _METHODS:
        faults.append(
            Fault("type", f"endpoint: method must be one of {sorted(_METHODS)}")
        )
    path = data.get("path")
    if "path" in data and not (isinstance(path, str) and path.startswith("/")):
        faults.append(
            Fault("type", "endpoint: path must be a string starting with '/'")
        )
    if "request" in data:
        faults += _typed_map_faults(data["request"], "endpoint.request")
    faults += tables_fault(data, "responses", "endpoint")
    for n, response in enumerate(tables(data, "responses", "endpoint"), 1):
        where = f"responses[{n}]"
        faults += check_keys(response, {"status"}, {"body", "change", "was"}, where)
        faults += change_faults(response, where)
        status = response.get("status")
        if "status" in response and not (
            isinstance(status, int)
            and not isinstance(status, bool)
            and 100 <= status <= 599
        ):
            faults.append(Fault("type", f"{where}: status must be an integer 100-599"))
        faults += str_field(response, "body", where)
    return faults


DATA_MODEL = BlockSpec(
    "data-model",
    "Entities with a key and relations to other entities",
    (
        "entity: list of {name, key, fields, relations}, one per entity",
        "  name       entity name (unique)",
        "  key        field that identifies a row; must be in fields",
        "  fields     {field name: type text, or {type, change, was}}",
        "  relations  optional list of {to, kind}",
        "    to    name of another entity in this block",
        "    kind  one-to-one, one-to-many, many-to-one, many-to-many",
        *LAYOUT_NOTE,
        *_CHANGE_NOTE,
    ),
    r"""data-model = data-model(
  entity: [
    {"name": "customer", "key": "id", "fields": {"id": "uuid", "email": "text"}},
    {
      "name": "order",
      "key": "id",
      "fields": {"id": "uuid", "customer_id": "uuid", "total": "cents"},
      "relations": [{"to": "customer", "kind": "many-to-one"}]
    },
  ],
)
""",
    validate_data_model,
)

ENDPOINT = BlockSpec(
    "endpoint",
    "One HTTP endpoint with its auth rule and responses",
    (
        "method      GET, POST, PUT, PATCH, DELETE, HEAD or OPTIONS",
        "path        starts with /",
        'auth        required; "none" must be written to mean public',
        "summary     optional one line",
        "request     optional {parameter: type text, or {type, change, was}}",
        "responses   list of {status, body, change, was}; status 100-599",
        *_CHANGE_NOTE,
    ),
    r"""endpoint = endpoint(
  method: "POST",
  path: "/orders",
  auth: "bearer",
  summary: "Create an order",
  request: {"customer_id": "uuid", "total": "cents"},
  responses: [
    {"status": 201, "body": "the new order"},
    {"status": 422, "body": "validation errors"},
  ],
)
""",
    validate_endpoint,
)
