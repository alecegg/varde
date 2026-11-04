"""HTML for data-model and endpoint blocks."""

from collections.abc import Mapping

from varde_learn.docs.pages.blocks_render.change import (
    FLAGS_HEAD,
    change_badge,
    change_name,
    change_of,
    change_table,
    copy_line,
    legend,
)
from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    badge,
    card,
    count_noun,
    esc,
)
from varde_learn.docs.pages.blocks_render.er import render_data_graph
from varde_learn.docs.pages.blocks_render.svg import copy_attr

# One changed row: (change, name used in the Copy text, was).
Changed = list[tuple[str, str, str]]


def _typed(value: object) -> tuple[str, str, str]:
    """`(type, change, was)` of a field or parameter value."""
    if isinstance(value, Mapping):
        return (str(value["type"]), *change_of(value))
    return (str(value), "", "")


def _typed_rows(
    items: Mapping[str, object], scope: str, mark_key: object, changed: Changed
) -> list[tuple[list[str], str, str, str]]:
    rows = []
    for name, value in items.items():
        kind, change, was = _typed(value)
        if change:
            changed.append((change, f"{scope}.{name}", was))
        key = badge("key", "vb-badge-key") if name == mark_key else ""
        cells = [change_name(esc(name), change, was), esc(kind)]
        rows.append(
            (cells + ([key] if mark_key is not None else []), change, was, name)
        )
    return rows


def _entity(entity: dict[str, object], changed: Changed) -> str:
    change, was = change_of(entity)
    name = str(entity["name"])
    if change:
        changed.append((change, name, was))
    rows = _typed_rows(as_dict(entity.get("fields")), name, entity["key"], changed)
    items = "".join(
        f"<li>&rarr; <strong>{esc(r['to'])}</strong> "
        f"{badge(r.get('kind', 'relation'), 'vb-rel')}</li>"
        for r in as_list(entity.get("relations"))
    )
    rel_html = f'<ul class="vb-relations">{items}</ul>' if items else ""
    title = change_name(esc(name), change, was)
    if change:
        title += f" {change_badge(change, was)}"
    return card(
        title,
        change_table(["field", "type", FLAGS_HEAD], rows, f"{name} fields") + rel_html,
        f"vd-change-card vd-change-{change}" if change else "",
    )


def _root(kind: str, parts: str, changed: Changed, summary: str) -> str:
    parts = f'<p class="vb-alt">{esc(summary)}</p>{parts}'
    if not changed:
        return f'<div class="vb {kind}">{parts}</div>'
    text = "\n".join(copy_line(*c) for c in changed)
    kinds = [c for c, _, _ in changed]
    return f'<div class="vb {kind}"{copy_attr(text)}>{parts}{legend(kinds)}</div>'


def render_data_model(data: dict[str, object]) -> str:
    if data.get("layout") == "graph":
        return render_data_graph(data)
    changed: Changed = []
    entities = as_list(data["entity"])
    cards = "".join(_entity(e, changed) for e in entities)
    relations = sum(len(as_list(e.get("relations"))) for e in entities)
    summary = (
        f"{count_noun(len(entities), 'entity', 'entities')}, "
        f"{count_noun(relations, 'relation', 'relations')}"
    )
    return _root("data-model", f'<div class="vb-grid">{cards}</div>', changed, summary)


def _responses(data: dict[str, object], changed: Changed) -> str:
    rows = []
    for r in as_list(data["responses"]):
        change, was = change_of(r)
        if change:
            changed.append((change, f"response {r['status']}", was))
        cells = [badge(r["status"], "vb-status"), esc(r.get("body", ""))]
        rows.append((cells, change, was, f"response {r['status']}"))
    return change_table(["status", "body"], rows, "Responses")


def render_endpoint(data: dict[str, object]) -> str:
    changed: Changed = []
    change, was = change_of(data)
    if change:
        changed.append((change, f"{data['method']} {data['path']}", was))
    auth = str(data["auth"])
    auth_kind = "vb-auth-none" if auth == "none" else "vb-auth"
    path = change_name(f"<code>{esc(data['path'])}</code>", change, was, "span")
    head = f"{badge(data['method'], 'vb-method')} {path} "
    head += badge("auth: " + auth, auth_kind)
    if change:
        head += f" {change_badge(change, was)}"
    parts = []
    if "summary" in data:
        parts.append(f"<p>{esc(data['summary'])}</p>")
    request = data.get("request")
    if isinstance(request, dict) and request:
        rows = _typed_rows(request, "request", None, changed)
        parts.append(change_table(["request", "type"], rows, "Request"))
    parts.append(_responses(data, changed))
    kind = f"vd-change-card vd-change-{change}" if change else ""
    summary = f"{data['method']} {data['path']}: auth {auth}, "
    summary += count_noun(len(as_list(data["responses"])), "response", "responses")
    return _root("endpoint", card(head, "".join(parts), kind), changed, summary)
