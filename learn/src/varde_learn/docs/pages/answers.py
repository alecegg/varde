"""Server-side validation of an `answer` row against its component's own props.

The client names a block id, a value and a text; nothing it sends is trusted.
The block is looked up in the page text (a `ui` statement), its
`AnswerSchema` gives the value type and allowed set, and sizes are capped.
Pure functions; no I/O.
"""

from __future__ import annotations

import json
import math

from varde_learn.docs.pages.blocks.check import check_props
from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.inputs import MAX_VALUE_JSON, check_form_value
from varde_learn.docs.pages.blocks.inputs_ordered import check_slider_value
from varde_learn.docs.pages.blocks.spec import AnswerSchema
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.comments import CONTROLS
from varde_learn.docs.pages.lines import parse_lines

MAX_ANSWER_TEXT = 8000
MAX_ANSWER_ITEM = 600
MAX_LIST = 100
_TEXT_REQUIRED = {"commented"}  # a verdict that is only meaningful with a reason


def _statement_props(doc_text: str, item: str) -> tuple[str, dict[str, object]] | None:
    for fence in find_fences(doc_text, frozenset({"ui"})):
        for statement in parse_lines(fence.body).statements:
            if statement.id != item:
                continue
            faults = check_props(statement.component, statement.props, 0)
            return None if faults else (statement.component, statement.props)
    return None


def answer_schema(doc_text: str, item: str) -> AnswerSchema | None:
    """The schema of the answerable block `item`, or None when there is none."""
    found = _statement_props(doc_text, item)
    if found is None:
        return None
    component = COMPONENTS.get(found[0])
    if component is None or component.answer_schema is None:
        return None
    return component.answer_schema(found[1])


def _allowed_ok(kind: str, value: object, allowed: tuple[str, ...]) -> bool:
    members = value if kind == "list" else [value]
    if not isinstance(members, list) or len(members) > MAX_LIST:
        return False
    if kind == "list" and (not members or len(set(map(str, members))) != len(members)):
        return False  # a picked set: at least one member, each once
    if not allowed:
        return all(isinstance(m, str) and len(m) <= MAX_ANSWER_ITEM for m in members)
    return all(isinstance(m, str) and m in allowed for m in members)


def _number_ok(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _ranking_ok(value: object, allowed: tuple[str, ...]) -> bool:
    """A permutation of the declared items: each exactly once."""
    return _allowed_ok("list", value, allowed) and len(value) == len(allowed)  # type: ignore[arg-type]


def _check_value(schema: AnswerSchema, value: object) -> None:
    kind = schema.kind
    if kind == "form":
        check_form_value(schema.shape, value)
        ok = True
    elif kind == "number":
        ok = _number_ok(value)
        if ok and schema.bounds is not None:
            check_slider_value(schema.bounds, value)  # names the range or step
    elif kind == "ranking":
        ok = _ranking_ok(value, schema.allowed)
    elif kind in {"verdict", "string", "list"}:
        ok = _allowed_ok(kind, value, schema.allowed)
    else:
        raise ValueError(f"answer kind {kind!r} is not supported")
    if not ok:
        shown = f"one of {', '.join(schema.allowed)}" if schema.allowed else kind
        raise ValueError(f"value must be {shown}")
    members = value if isinstance(value, list) else [value]
    if any(isinstance(m, str) and CONTROLS.search(m) for m in members):
        raise ValueError("value holds control characters")
    if (
        len(json.dumps(value, ensure_ascii=kind not in {"form", "ranking"}))
        > MAX_VALUE_JSON
    ):
        raise ValueError("value too large")


def validate_answer(doc_text: str, item: str, value: object, text: str) -> None:
    """Raise ValueError unless `item` is an answerable block and the answer fits it."""
    if not item or len(item) > MAX_ANSWER_ITEM:
        raise ValueError(f"answer item needs 1-{MAX_ANSWER_ITEM} characters")
    if len(text) > MAX_ANSWER_TEXT:
        raise ValueError(f"text longer than {MAX_ANSWER_TEXT} characters")
    if CONTROLS.search(text) or CONTROLS.search(item):
        raise ValueError("text holds control characters")
    schema = answer_schema(doc_text, item)
    if schema is None:
        raise ValueError(f"unknown answer block {item!r}")
    _check_value(schema, value)
    if text.strip() and "text" not in schema.fields:
        raise ValueError(f"block {item!r} takes no text")
    needs_text = schema.kind == "verdict" and value in _TEXT_REQUIRED
    if needs_text and not text.strip():
        raise ValueError("a comment needs text")


def answer_value(row: dict) -> object:
    """The value of an answer row; an old `decision` row carries its verdict."""
    return row.get("value") if row.get("kind") == "answer" else row.get("verdict")
