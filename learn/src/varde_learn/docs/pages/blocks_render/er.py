"""HTML and SVG for the data-model `graph` layout.

The drawing is server-laid-out (`er_layout`): entity boxes on a grid with a line per
relation and cardinality labels at both ends. It is `aria-hidden`; the relation text
list and the full entity cards below it carry the same facts, and are all a narrow
or printed page shows. Entities are hooked by index (`data-entity`, `data-ends`) so
`static/er.js` can highlight a card's relations without reading any name.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.change import (
    FLAGS_HEAD,
    GLYPHS,
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
    card,
    count_noun,
    esc,
)
from varde_learn.docs.pages.blocks_render.er_layout import (
    BOX_W,
    HEAD_H,
    ROW_H,
    Box,
    Grid,
    Point,
    label_point,
    place,
    route,
    visible_rows,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr

TEXT_CHARS = 30
ENDS = {
    "one-to-one": ("1", "1"),
    "one-to-many": ("1", "n"),
    "many-to-one": ("n", "1"),
    "many-to-many": ("n", "n"),
}
Entity = Mapping[str, object]


@dataclass(frozen=True)
class Relation:
    source: int
    target: int
    kind: str
    field: str = ""  # set when the relation is inferred from this field

    @property
    def ends(self) -> tuple[str, str]:
        return ENDS.get(self.kind, ("", ""))


def _names(entities: Sequence[Entity]) -> list[str]:
    return [str(e["name"]) for e in entities]


def declared_relations(entities: Sequence[Entity]) -> list[Relation]:
    index = {name: i for i, name in enumerate(_names(entities))}
    return [
        Relation(i, index[str(r["to"])], str(r.get("kind", "")))
        for i, entity in enumerate(entities)
        for r in as_list(entity.get("relations"))
        if str(r["to"]) in index
    ]


def inferred_relations(
    entities: Sequence[Entity], declared: list[Relation]
) -> list[Relation]:
    """A field `<entity>_id` points at that entity unless a relation joins them."""
    folded = {name.casefold(): i for i, name in enumerate(_names(entities))}
    joined = {frozenset((r.source, r.target)) for r in declared}
    found: list[Relation] = []
    for i, entity in enumerate(entities):
        for field in as_dict(entity.get("fields")):
            stem = field[:-3].casefold() if field.casefold().endswith("_id") else ""
            target = folded.get(stem, i)
            pair = frozenset((i, target))
            if target == i or field == entity["key"] or pair in joined:
                continue
            joined.add(pair)
            found.append(Relation(i, target, "many-to-one", field))
    return found


def relation_text(names: list[str], rel: Relation) -> str:
    source, target = names[rel.source], names[rel.target]
    left, right = rel.ends
    middle = f"{left} to {right}" if left else "relates to"
    note = f" (inferred from field {rel.field})" if rel.field else ""
    return f"{source} {middle} {target}{note}"


def _short(text: str) -> str:
    return text if len(text) <= TEXT_CHARS else text[: TEXT_CHARS - 1] + "…"


def _glyph(change: str) -> str:
    return f"{GLYPHS[change]} " if change else ""


def _text(x: float, y: float, cls: str, body: str) -> str:
    return f'<text class="{cls}" x="{x:g}" y="{y:g}">{esc(body)}</text>'


def _field_line(name: str, value: object, key: object) -> tuple[str, str]:
    kind, change = (
        (str(value["type"]), str(value.get("change", "")))
        if isinstance(value, Mapping)
        else (str(value), "")
    )
    mark = "* " if name == key else ""
    cls = "vd-er-field" + (f" vd-change-{change}" if change else "")
    cls += " vd-er-keyed" if mark else ""
    return cls, _short(f"{_glyph(change)}{mark}{name}: {kind}")


def _box(box: Box, entity: Entity) -> str:
    change = change_of(entity)[0]
    fields = as_dict(entity.get("fields"))
    shown, hidden = visible_rows(len(fields))
    cls = "vd-er-box" + (f" vd-change-{change}" if change else "")
    parts = [
        (
            f'<rect class="{cls}" x="{box.x:g}" y="{box.y:g}" '
            f'width="{BOX_W:g}" height="{box.h:g}" rx="6"/>'
        ),
        (
            f'<rect class="vd-er-head" x="{box.x:g}" y="{box.y:g}" '
            f'width="{BOX_W:g}" height="{HEAD_H:g}" rx="6"/>'
        ),
        _text(
            box.x + 10,
            box.y + 20,
            "vd-er-name",
            _short(_glyph(change) + str(entity["name"])),
        ),
    ]
    for n, (name, value) in enumerate(list(fields.items())[:shown]):
        cls_, body = _field_line(name, value, entity["key"])
        parts.append(_text(box.x + 10, box.y + HEAD_H + ROW_H * (n + 0.75), cls_, body))
    if hidden:
        more = _text(
            box.x + 10,
            box.y + HEAD_H + ROW_H * (shown + 0.75),
            "vd-er-more",
            f"+{hidden} more",
        )
        parts.append(more)
    return f'<g class="vd-er-node" data-entity="{box.index}">{"".join(parts)}</g>'


def _path(points: list[Point]) -> str:
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in points)


def _edge(grid: Grid, rel: Relation, lane: int) -> str:
    points = route(grid, grid.boxes[rel.source], grid.boxes[rel.target], lane)
    cls = "vd-er-line" + (" vd-er-inferred" if rel.field else "")
    parts = [f'<path class="{cls}" d="{_path(points)}"/>']
    for at_start, label in zip((True, False), rel.ends, strict=True):
        if label:
            x, y = label_point(points, at_start)
            parts.append(_text(x, y, "vd-er-end", label))
    ends = f"{rel.source} {rel.target}"
    return f'<g class="vd-er-edge" data-ends="{ends}">{"".join(parts)}</g>'


def _drawing(entities: Sequence[Entity], rels: list[Relation]) -> str:
    grid = place([len(as_dict(e.get("fields"))) for e in entities])
    edges = "".join(_edge(grid, r, lane) for lane, r in enumerate(rels))
    boxes = "".join(_box(b, e) for b, e in zip(grid.boxes, entities, strict=True))
    return (
        f'<svg class="vd-er-svg" viewBox="0 0 {grid.width:g} {grid.height:g}" '
        f'width="{grid.width:g}" height="{grid.height:g}" aria-hidden="true" '
        f'focusable="false">{edges}{boxes}</svg>'
    )


def _anchor(digest: str, index: int) -> str:
    return f"vd-er-{digest}-{index}"


def _rows(
    entity: Entity, fk: dict[str, tuple[int, str]], digest: str
) -> list[tuple[list[str], str, str, str]]:
    key = entity["key"]
    rows = []
    for name, value in as_dict(entity.get("fields")).items():
        kind = str(value["type"]) if isinstance(value, Mapping) else str(value)
        change, was = change_of(value) if isinstance(value, Mapping) else ("", "")
        label = change_name(esc(name), change, was)
        if name in fk:
            target, target_name = fk[name]
            label = (
                f'<a class="vd-er-fk" href="#{_anchor(digest, target)}">{label} '
                f"&rarr; {esc(target_name)}</a>"
            )
        marks = '<span class="vb-badge vb-badge-key">key</span>' if name == key else ""
        rows.append(([label, esc(kind), marks], change, was, name))
    return rows


def _fk_links(
    index: int, names: list[str], rels: list[Relation]
) -> dict[str, tuple[int, str]]:
    """Field name to `(target entity, its name)` for every `<target>_id` field."""
    found = {}
    for r in rels:
        if r.source == index:
            found[r.field or f"{names[r.target]}_id"] = (r.target, names[r.target])
    return found


def _card(
    index: int, entity: Entity, names: list[str], rels: list[Relation], digest: str
) -> str:
    change, was = change_of(entity)
    title = change_name(esc(entity["name"]), change, was)
    if change:
        title += f" {change_badge(change, was)}"
    rows = _rows(entity, _fk_links(index, names, rels), digest)
    kind = f"vd-change-card vd-change-{change}" if change else ""
    fields = change_table(
        ["field", "type", FLAGS_HEAD], rows, f"{entity['name']} fields"
    )
    body = card(title, fields, kind)
    return (
        f'<div class="vd-er-card" id="{_anchor(digest, index)}" '
        f'data-entity="{index}">{body}</div>'
    )


def _relation_list(names: list[str], rels: list[Relation]) -> str:
    if not rels:
        return '<p class="vb-alt vd-er-none">No relations.</p>'
    items = "".join(
        f'<li class="vd-er-rel" data-ends="{r.source} {r.target}">'
        f"{esc(relation_text(names, r))}</li>"
        for r in rels
    )
    return '<ul class="vd-er-relations" aria-label="Relations">' + items + "</ul>"


def _copy_text(
    entities: Sequence[Entity], names: list[str], rels: list[Relation]
) -> str:
    lines = []
    for entity in entities:
        fields = ", ".join(as_dict(entity.get("fields")))
        change, was = change_of(entity)
        head = f"{entity['name']} (key {entity['key']}): {fields}"
        lines.append(
            head if not change else f"{head} [{copy_line(change, 'entity', was)}]"
        )
    lines += [relation_text(names, r) for r in rels]
    return "\n".join(lines)


def _changes(entities: Sequence[Entity]) -> list[str]:
    found = []
    for entity in entities:
        found.append(change_of(entity)[0])
        found += [
            change_of(v)[0]
            for v in as_dict(entity.get("fields")).values()
            if isinstance(v, Mapping)
        ]
    return [c for c in found if c]


def render_data_graph(data: dict[str, object]) -> str:
    entities = as_list(data["entity"])
    names = _names(entities)
    digest = hashlib.sha1("\0".join(names).encode()).hexdigest()[:8]  # noqa: S324
    declared = declared_relations(entities)
    rels = declared + inferred_relations(entities, declared)
    drawing = (
        '<div class="vd-er-view" role="region" tabindex="0" '
        'aria-label="Entity relationship drawing; the relation list below '
        'has the same facts">'
        f"{_drawing(entities, rels)}</div>"
    )
    cards = "".join(_card(i, e, names, rels, digest) for i, e in enumerate(entities))
    changes = _changes(entities)
    tail = legend(changes) if changes else ""
    summary = (
        f"{count_noun(len(entities), 'entity', 'entities')}, "
        f"{count_noun(len(rels), 'relation', 'relations')}"
    )
    return (
        f'<div class="vb data-model vd-er"'
        f"{copy_attr(_copy_text(entities, names, rels))}>"
        f'<p class="vb-alt">{esc(summary)}</p>{drawing}{_relation_list(names, rels)}'
        f'<div class="vd-er-cards">{cards}</div>{tail}</div>'
    )
