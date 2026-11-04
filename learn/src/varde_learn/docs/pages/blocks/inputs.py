"""Components `choice`, `form` and `comment`: props checks and form-value checks.

These are line-syntax components (a `ui` fence); none has a TOML fence form. The
renderers and answer schemas live in `blocks_render.inputs`. Pure functions.
"""

import math
import re

from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    is_number,
    str_field,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec
from varde_learn.docs.pages.comments import CONTROLS

MAX_OPTIONS = 50
MAX_FIELDS = 30
MAX_LABEL = 200
MAX_DETAIL = 1000
MAX_VALUE_JSON = 8000  # longest JSON text of one answer value
MAX_VALUE = 600  # an option value or a text field's longest allowed answer
FIELD_TYPES = ("text", "number", "select", "checkbox")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_TYPE_KEYS = {
    "text": {"maxlength"},
    "number": {"min", "max"},
    "select": {"options"},
    "checkbox": set(),
}


def finite(value: object) -> bool:
    """True for a real number (not a bool) that is neither NaN nor infinite."""
    if not is_number(value):
        return False
    try:
        return math.isfinite(value)  # type: ignore[arg-type]
    except OverflowError:
        return False


def text_fault(value: object, where: str, limit: int) -> list[Fault]:
    """A fault unless `value` is a non-empty string within `limit`, no controls."""
    if not isinstance(value, str) or not value.strip():
        return [Fault("type", f"{where} must be a non-empty string")]
    if len(value) > limit or CONTROLS.search(value):
        return [
            Fault("type", f"{where} must be at most {limit} characters, no controls")
        ]
    return []


def option_label_value(option: object) -> tuple[str, str]:
    """(label, value) of a validated option: a string, or a table with a label."""
    if isinstance(option, dict):
        label = str(option.get("label", ""))
        return label, str(option.get("value", label))
    return str(option), str(option)


def option_faults(option: object, where: str) -> list[Fault]:
    if isinstance(option, str):
        return text_fault(option, where, MAX_VALUE)
    if not isinstance(option, dict):
        return [Fault("type", f"{where} must be a string or a table with a label")]
    faults = check_keys(option, {"label"}, {"detail", "value", "recommended"}, where)
    faults += text_fault(option.get("label"), f"{where}.label", MAX_LABEL)
    if "recommended" in option and not isinstance(option["recommended"], bool):
        faults.append(Fault("type", f"{where}.recommended must be true or false"))
    for key, limit in (("detail", MAX_DETAIL), ("value", MAX_VALUE)):
        if key in option:
            faults += text_fault(option[key], f"{where}.{key}", limit)
    return faults


def _options_faults(data: dict[str, object]) -> list[Fault]:
    options = data.get("options")
    if "options" not in data:
        return []
    if not isinstance(options, list) or not 0 < len(options) <= MAX_OPTIONS:
        return [Fault("type", f"choice.options must be a list of 1-{MAX_OPTIONS}")]
    faults: list[Fault] = []
    for index, option in enumerate(options, start=1):
        faults += option_faults(option, f"choice.options[{index}]")
    if faults:
        return faults
    values = [option_label_value(o)[1] for o in options]
    faults = [
        Fault("option-duplicate", f"choice.options: value '{v}' is listed twice")
        for v in duplicates(values)
    ]
    marked = [o for o in options if isinstance(o, dict) and o.get("recommended")]
    if len(marked) > 1:
        faults.append(
            Fault(
                "recommended-many", "choice.options: at most one option is recommended"
            )
        )
    return faults


def _flag_faults(
    data: dict[str, object], keys: tuple[str, ...], where: str
) -> list[Fault]:
    return [
        Fault("type", f"{where}.{key} must be true or false")
        for key in keys
        if key in data and not isinstance(data[key], bool)
    ]


def validate_choice(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(
        data, {"question", "options"}, {"multiple", "comment"}, "choice"
    )
    faults += str_field(data, "question", "choice")
    faults += _flag_faults(data, ("multiple", "comment"), "choice")
    return faults + _options_faults(data)


def validate_comment(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"label"}, {"submit"}, "comment")
    return (
        faults
        + str_field(data, "label", "comment")
        + str_field(data, "submit", "comment")
    )


def _limit_fault(value: object, where: str, low: int, high: int) -> list[Fault]:
    ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    return [] if ok else [Fault("type", f"{where} must be a whole number {low}-{high}")]


def _bound_faults(field: dict[str, object], where: str) -> list[Fault]:
    faults: list[Fault] = []
    for key in ("min", "max"):
        value = field.get(key)
        if key in field and not finite(value):
            faults.append(Fault("type", f"{where}.{key} must be a finite number"))
    low, high = field.get("min"), field.get("max")
    if is_number(low) and is_number(high) and low > high:  # type: ignore[operator]
        faults.append(Fault("range", f"{where}: min is above max"))
    return faults


def _select_faults(field: dict[str, object], where: str) -> list[Fault]:
    options = field.get("options")
    if "options" not in field:
        return [Fault("missing-key", f"{where}: select needs 'options'")]
    if not isinstance(options, list) or not 0 < len(options) <= MAX_OPTIONS:
        return [Fault("type", f"{where}.options must be a list of 1-{MAX_OPTIONS}")]
    faults: list[Fault] = []
    for option in options:
        faults += text_fault(option, f"{where}.options", MAX_VALUE)
    names = [o for o in options if isinstance(o, str)]
    return faults + [
        Fault("option-duplicate", f"{where}.options: '{o}' is listed twice")
        for o in duplicates(names)
    ]


def _field_faults(field: object, index: int) -> list[Fault]:
    where = f"form.fields[{index}]"
    if not isinstance(field, dict):
        return [Fault("type", f"{where} must be a table")]
    kind = field.get("type")
    if kind not in FIELD_TYPES:
        return [Fault("type", f"{where}.type must be one of {', '.join(FIELD_TYPES)}")]
    optional = {"required", *_TYPE_KEYS[kind]}
    faults = check_keys(field, {"name", "label", "type"}, optional, where)
    faults += text_fault(field.get("label"), f"{where}.label", MAX_LABEL)
    name = field.get("name")
    if not (isinstance(name, str) and FIELD_NAME.match(name)):
        faults.append(Fault("type", f"{where}.name must match {FIELD_NAME.pattern}"))
    faults += _flag_faults(field, ("required",), where)
    if kind == "text" and "maxlength" in field:
        faults += _limit_fault(field["maxlength"], f"{where}.maxlength", 1, MAX_VALUE)
    if kind == "number":
        faults += _bound_faults(field, where)
    if kind == "select":
        faults += _select_faults(field, where)
    return faults


def _field_json_bound(field: dict[str, object]) -> int:
    """Most JSON characters one field's value can take: quotes, escapes, key."""
    kind = field.get("type")
    if kind == "text":
        longest = int(field.get("maxlength", MAX_VALUE))  # type: ignore[call-overload]
    elif kind == "select":
        options = field.get("options")
        names = options if isinstance(options, list) else []
        longest = max((len(o) for o in names if isinstance(o, str)), default=0)
    else:
        longest = 0
    return (
        2 * longest + len(str(field.get("name", ""))) + 40
    )  # 40: number or bool, glue


def _size_faults(fields: list[object]) -> list[Fault]:
    rows = [f for f in fields if isinstance(f, dict)]
    bound = sum(_field_json_bound(f) for f in rows)
    if bound <= MAX_VALUE_JSON:
        return []
    return [
        Fault(
            "size",
            f"form: fields can add up to {bound} characters of answer; "
            f"the limit is {MAX_VALUE_JSON} (lower maxlength or drop fields)",
        )
    ]


def validate_form(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"fields"}, {"title", "submit"}, "form")
    faults += str_field(data, "title", "form") + str_field(data, "submit", "form")
    fields = data.get("fields")
    if "fields" not in data:
        return faults
    if not isinstance(fields, list) or not 0 < len(fields) <= MAX_FIELDS:
        return faults + [Fault("type", f"form.fields must be a list of 1-{MAX_FIELDS}")]
    for index, field in enumerate(fields, start=1):
        faults += _field_faults(field, index)
    names = [f["name"] for f in fields if isinstance(f, dict) and "name" in f]
    faults += _size_faults(fields)
    return faults + [
        Fault("field-duplicate", f"form.fields: name '{n}' is used twice")
        for n in duplicates([n for n in names if isinstance(n, str)])
    ]


def _text_value(field: dict[str, object], value: object) -> None:
    limit = int(field.get("maxlength", MAX_VALUE))  # type: ignore[call-overload]
    if not isinstance(value, str) or len(value) > limit or CONTROLS.search(value):
        raise ValueError(
            f"field {field['name']!r} must be text up to {limit} characters"
        )
    if field.get("required") and not value.strip():
        raise ValueError(f"field {field['name']!r} is required")


def _number_value(field: dict[str, object], value: object) -> None:
    name = field["name"]
    if value is None and not field.get("required"):
        return
    if not finite(value):
        raise ValueError(f"field {name!r} must be a finite number")
    low, high = field.get("min"), field.get("max")
    if is_number(low) and value < low:  # type: ignore[operator]
        raise ValueError(f"field {name!r} is below {low}")
    if is_number(high) and value > high:  # type: ignore[operator]
        raise ValueError(f"field {name!r} is above {high}")


def check_form_value(fields: tuple[dict[str, object], ...], value: object) -> None:
    """Raise ValueError unless `value` holds exactly the form's fields, each valid."""
    if not isinstance(value, dict):
        raise ValueError("form value must be an object")  # noqa: TRY004
    names = {str(f["name"]) for f in fields}
    if set(value) != names:
        raise ValueError("form value must hold exactly the form's fields")
    for field in fields:
        got, kind = value[str(field["name"])], field["type"]
        if kind == "text":
            _text_value(field, got)
        elif kind == "number":
            _number_value(field, got)
        elif kind == "select" and got == "" and not field.get("required"):
            continue  # the blank first option of an optional select
        elif kind == "select" and got not in field["options"]:  # type: ignore[operator]
            raise ValueError(f"field {field['name']!r} must be one of its options")
        elif kind == "checkbox" and not isinstance(got, bool):
            raise ValueError(f"field {field['name']!r} must be true or false")
        elif kind == "checkbox" and field.get("required") and not got:
            raise ValueError(f"field {field['name']!r} is required")


CHOICE = BlockSpec(
    "choice",
    "A question answered by picking one option, or several",
    (
        "question  required text",
        "options   required list: a string, or a table (label, detail, value)",
        "          recommended: true on one table shows a Recommended badge",
        "multiple  optional true to allow several picks; default one",
        "comment   optional true to add a free-text box",
    ),
    r"""choice = choice(
  question: "Which database?",
  comment: true,
  options: [
    {"label": "SQLite", "detail": "No server, one file", "recommended": true},
    {"label": "Postgres", "detail": "Shared server", "value": "postgres"},
  ],
)
""",
    validate_choice,
)

FORM = BlockSpec(
    "form",
    "Several fields (text, number, select, checkbox) sent with one submit",
    (
        "title    optional text",
        "submit   optional button label; default Submit",
        "fields: list of {name, label, type, ...}; type text|number|select|checkbox",
        "  required  optional true; a checkbox must then be ticked",
        "  maxlength  text only, up to 600",
        "  min, max   number only, finite bounds",
        "  options    select only, list of text; a blank choice comes first",
    ),
    r"""form = form(
  title: "Rollout settings",
  submit: "Save",
  fields: [
    {"name": "owner", "label": "Owner", "type": "text", "required": true,
     "maxlength": 40},
    {"name": "replicas", "label": "Replicas", "type": "number", "min": 1, "max": 10},
    {"name": "region", "label": "Region", "type": "select", "options": ["eu", "us"]},
    {"name": "notify", "label": "Notify the team", "type": "checkbox"},
  ],
)
""",
    validate_form,
)

COMMENT = BlockSpec(
    "comment",
    "A free-text box whose text is stored as the page's answer",
    (
        "label   required text shown above the box",
        "submit  optional button label; default Send",
    ),
    r"""comment = comment(
  label: "Anything we missed?",
  submit: "Send",
)
""",
    validate_comment,
)
