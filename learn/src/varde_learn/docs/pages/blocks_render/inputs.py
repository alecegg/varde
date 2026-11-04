"""HTML and answer schemas for `choice`, `form` and `comment`.

The server writes the whole widget as escaped HTML; `static/recap.js` hydrates
it through `data-component` and the whitelisted `data-props` JSON (written with
`html.escape`) and posts one `answer` row. Option values and field names are
the only strings the client sends back, and the server checks them again.
"""

import json
from collections.abc import Mapping

from varde_learn.docs.pages.blocks.inputs import option_label_value
from varde_learn.docs.pages.blocks.spec import AnswerSchema
from varde_learn.docs.pages.blocks_render.common import as_dict, as_list, card, esc

Props = dict[str, object]
MAX_NOTE = 8000  # the server's cap on an answer's text


def mount(kind: str, props: Mapping[str, object], body: str) -> str:
    """The hydration root: component name and JSON props as escaped attributes."""
    attr = esc(json.dumps(props, ensure_ascii=False))
    root = f'<div class="vb {kind}" data-component="{kind}" data-props="{attr}">'
    return f"{root}{body}</div>"


def footer(kind: str, label: str, block_id: str | None) -> str:
    return (
        f'<button type="submit" class="{kind}-send">{esc(label)}</button>'
        f'<span class="{kind}-state" aria-live="polite"></span>'
        f'<p class="{kind}-error" id="{kind}-error-{esc(block_id)}" role="alert"></p>'
    )


def _option(option: object, input_type: str, group: str, index: int) -> str:
    label, value = option_label_value(option)
    detail = as_dict(option).get("detail")
    shown = f'<span class="choice-detail">{esc(detail)}</span>' if detail else ""
    rec_id = f"{group}-rec-{index}"
    recommended = as_dict(option).get("recommended") is True
    badge = (
        f'<span class="choice-rec" id="{esc(rec_id)}">Recommended</span>'
        if recommended
        else ""
    )
    described = f' aria-describedby="{esc(rec_id)}"' if recommended else ""
    return (
        f'<label class="choice-option"><input type="{input_type}" name="{esc(group)}" '
        f'value="{esc(value)}" aria-required="true"{described}>'
        '<span class="choice-body">'
        f'<span class="choice-label">{esc(label)}</span>{badge}{shown}</span></label>'
    )


def _text_area(kind: str, label: str) -> str:
    return (
        f'<label class="{kind}-note"><span>{esc(label)}</span>'
        f'<textarea class="{kind}-text" rows="3" maxlength="{MAX_NOTE}">'
        "</textarea></label>"
    )


def render_choice(data: Props, block_id: str | None) -> str:
    multiple = data.get("multiple") is True
    input_type = "checkbox" if multiple else "radio"
    group = f"choice-{block_id or ''}"
    options = "".join(
        _option(o, input_type, group, i)
        for i, o in enumerate(as_list(data.get("options")), start=1)
    )
    note = _text_area("choice", "Comment") if data.get("comment") is True else ""
    inner = (
        f'<form class="choice-item" data-item="{esc(block_id)}" novalidate>'
        f'<fieldset class="choice-group" '
        f'aria-describedby="choice-error-{esc(block_id)}">'
        f'<legend class="choice-question">{esc(data["question"])}</legend>'
        f'<div class="choice-options"><div class="choice-grid">{options}</div></div>'
        f"</fieldset>"
        f"{note}{footer('choice', 'Send', block_id)}</form>"
    )
    props = {"multiple": multiple, "comment": data.get("comment") is True}
    return mount("choice", props, card("Choice", inner))


def _hint(field: dict) -> str:
    """The limit a reader can act on: text length or number range (else empty)."""
    if field["type"] == "text" and "maxlength" in field:
        return f"Up to {field['maxlength']} characters."
    if field["type"] != "number":
        return ""
    low, high = field.get("min"), field.get("max")
    if low is not None and high is not None:
        return f"From {low} to {high}."
    if low is not None:
        return f"At least {low}."
    return f"At most {high}." if high is not None else ""


def _control(field: dict, attrs: str) -> str:
    kind = field["type"]
    if kind == "checkbox":
        return f'<input type="checkbox" {attrs}>'
    if kind == "select":
        blank = '<option value=""></option>'
        choices = blank + "".join(
            f"<option>{esc(o)}</option>" for o in as_list(field["options"])
        )
        return f"<select {attrs}>{choices}</select>"
    if kind == "number":
        bounds = "".join(
            f' {k}="{esc(field[k])}"' for k in ("min", "max") if k in field
        )
        return f'<input type="number" step="any" {attrs}{bounds}>'
    limit = esc(field.get("maxlength", 600))
    return f'<input type="text" maxlength="{limit}" {attrs}>'


def _field(field: dict, group: str) -> str:
    name, kind = esc(field["name"]), field["type"]
    hint, hint_id = _hint(field), f"{esc(group)}-{name}-hint"
    attrs = f'data-field="{name}" name="{esc(group)}-{name}"'
    if field.get("required") is True:
        attrs += ' aria-required="true"'
    if hint:
        attrs += f' aria-describedby="{hint_id}"'
    control = _control(field, attrs)
    star = " *" if field.get("required") is True else ""
    label = f'<span class="form-label">{esc(field["label"])}{star}</span>'
    inner = control + label if kind == "checkbox" else label + control
    shown = f'<span class="form-hint" id="{hint_id}">{esc(hint)}</span>' if hint else ""
    return (
        f'<div class="form-row form-{kind}">'
        f'<label class="form-field">{inner}</label>{shown}</div>'
    )


def _client_field(field: dict) -> dict[str, object]:
    """The keys the client needs to read a field back (a whitelist, not the table)."""
    keys = ("name", "type", "required", "min", "max")
    return {k: field[k] for k in keys if k in field}


def render_form(data: Props, block_id: str | None) -> str:
    fields = [as_dict(f) for f in as_list(data.get("fields"))]
    group = f"form-{block_id or ''}"
    title = (
        f'<p class="form-title">{esc(data["title"])}</p>' if data.get("title") else ""
    )
    inner = (
        f'<form class="form-item" data-item="{esc(block_id)}" novalidate>{title}'
        '<div class="form-body"><div class="form-grid">'
        f"{''.join(_field(f, group) for f in fields)}</div></div>"
        '<p class="form-remaining" aria-live="polite"></p>'
        f"{footer('form', str(data.get('submit', 'Submit')), block_id)}</form>"
    )
    props = {"fields": [_client_field(f) for f in fields]}
    return mount("form", props, card("Form", inner))


def _comment_field(label: str, block_id: str | None) -> str:
    """Stacked label, textarea and a counter (the live region speaks at thresholds)."""
    bid = esc(block_id)
    return (
        '<div class="comment-field">'
        f'<label class="comment-note" for="comment-text-{bid}">{esc(label)}</label>'
        f'<textarea class="comment-text" id="comment-text-{bid}" rows="4" '
        f'maxlength="{MAX_NOTE}" aria-describedby="comment-count-{bid}"></textarea>'
        f'<span class="comment-count" id="comment-count-{bid}">0 / {MAX_NOTE}</span>'
        '<span class="comment-announce" aria-live="polite"></span></div>'
    )


def render_comment(data: Props, block_id: str | None) -> str:
    inner = (
        f'<form class="comment-item" data-item="{esc(block_id)}" novalidate>'
        f"{_comment_field(str(data['label']), block_id)}"
        f"{footer('comment', str(data.get('submit', 'Send')), block_id)}</form>"
    )
    return mount("comment", {}, card("Comment", inner))


def choice_values(data: Props) -> tuple[str, ...]:
    """The answer value of each option, in order."""
    return tuple(option_label_value(o)[1] for o in as_list(data.get("options")))


def choice_answer_schema(data: Props) -> AnswerSchema:
    kind = "list" if data.get("multiple") is True else "string"
    fields = ("text",) if data.get("comment") is True else ()
    return AnswerSchema(kind, fields, choice_values(data))


def form_answer_schema(data: Props) -> AnswerSchema:
    return AnswerSchema(
        "form", (), (), tuple(as_dict(f) for f in as_list(data.get("fields")))
    )


def comment_answer_schema(data: Props) -> AnswerSchema:
    """The value is the fixed verdict `commented`; the reader's text is the answer."""
    return AnswerSchema("verdict", ("text",), ("commented",))
