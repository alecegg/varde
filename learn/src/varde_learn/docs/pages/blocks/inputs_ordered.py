"""Components `ranking` and `slider`: props checks and the slider value check.

Line-syntax components (a `ui` fence); neither has a TOML fence form. The
renderers and answer schemas live in `blocks_render.inputs_ordered`. Pure functions.
"""

import math

from varde_learn.docs.pages.blocks.inputs import (
    MAX_LABEL,
    MAX_OPTIONS,
    MAX_VALUE_JSON,
    finite,
    option_faults,
    option_label_value,
    text_fault,
)
from varde_learn.docs.pages.blocks.rules import Fault, check_keys, duplicates, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

MIN_ITEMS = 2
MAX_STEPS = 10000  # positions a slider can take; keeps the control usable
STEP_TOLERANCE = 1e-9  # in steps; absorbs float error such as 0.1 * 3
ULPS = 2  # float spacing allowed on top, so a huge min with a small step works


def _items_faults(data: dict[str, object]) -> list[Fault]:
    items = data.get("items")
    if "items" not in data:
        return []
    if not isinstance(items, list) or not MIN_ITEMS <= len(items) <= MAX_OPTIONS:
        message = f"ranking.items must be a list of {MIN_ITEMS}-{MAX_OPTIONS}"
        return [Fault("type", message)]
    faults: list[Fault] = []
    for index, item in enumerate(items, start=1):
        faults += option_faults(item, f"ranking.items[{index}]")
    if faults:
        return faults
    values = [option_label_value(i)[1] for i in items]
    faults = [
        Fault("option-duplicate", f"ranking.items: value '{v}' is listed twice")
        for v in duplicates(values)
    ]
    bound = sum(2 * len(v) + 4 for v in values) + 2  # quotes, escapes, commas
    if bound > MAX_VALUE_JSON:
        faults.append(
            Fault(
                "size",
                f"ranking: the answer can reach {bound} characters; the limit is "
                f"{MAX_VALUE_JSON} (shorten the values or drop items)",
            )
        )
    return faults


def validate_ranking(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"question", "items"}, set(), "ranking")
    return faults + str_field(data, "question", "ranking") + _items_faults(data)


def slider_bounds(data: dict[str, object]) -> tuple[float, float, float]:
    """(min, max, step) of validated slider props; the step defaults to 1."""
    return data["min"], data["max"], data.get("step", 1)  # type: ignore[return-value]


def _bound_faults(data: dict[str, object]) -> list[Fault]:
    faults = [
        Fault("type", f"slider.{key} must be a finite number")
        for key in ("min", "max", "step")
        if key in data and not finite(data[key])
    ]
    if faults or not {"min", "max"} <= data.keys():
        return faults
    low, high, step = slider_bounds(data)
    if low >= high:
        return [Fault("range", "slider: min must be below max")]
    if step <= 0 or step > high - low:
        return [Fault("range", "slider.step must be above 0 and within max - min")]
    if (high - low) / step > MAX_STEPS:
        return [Fault("range", f"slider: more than {MAX_STEPS} steps; raise the step")]
    return []


def _labels_faults(data: dict[str, object]) -> list[Fault]:
    labels = data.get("labels")
    if "labels" not in data:
        return []
    if not isinstance(labels, list) or len(labels) != 2:
        return [Fault("type", "slider.labels must be two texts: low end, high end")]
    return [
        fault
        for label in labels
        for fault in text_fault(label, "slider.labels", MAX_LABEL)
    ]


def validate_slider(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"label", "min", "max"}, {"step", "labels"}, "slider")
    faults += str_field(data, "label", "slider")
    return faults + _bound_faults(data) + _labels_faults(data)


def check_slider_value(bounds: tuple[float, float, float], value: object) -> None:
    """Raise ValueError unless `value` is a finite number inside the range on a step."""
    low, high, step = bounds
    if not finite(value):
        raise ValueError("value must be a finite number")
    if not low <= value <= high:  # type: ignore[operator]
        raise ValueError(f"value must be between {low:g} and {high:g}")
    steps = (value - low) / step  # type: ignore[operator]
    slack = max(STEP_TOLERANCE * step, ULPS * math.ulp(max(abs(low), abs(high))))
    if abs(steps - round(steps)) * step > slack:
        raise ValueError(f"value must be {low:g} plus a whole number of {step:g}")


RANKING = BlockSpec(
    "ranking",
    "A list the reader puts in order; the answer is the ids in ranked order",
    (
        "question  required text",
        "items     required list of 2-50: a string, or a table (label, detail, value)",
        "          the list starts in the order given; drag, or use the move buttons",
    ),
    r"""ranking = ranking(
  question: "Order by urgency",
  items: [
    {"label": "Fix login", "value": "login"},
    {"label": "Speed up search", "detail": "p95 is 2 s", "value": "search"},
    {"label": "New logo", "value": "logo"},
  ],
)
""",
    validate_ranking,
)

SLIDER = BlockSpec(
    "slider",
    "A number picked on a range; the answer is one number on a step",
    (
        "label   required text",
        "min     required finite number",
        "max     required finite number above min",
        "step    optional number above 0, default 1; answers are min plus whole steps",
        "labels  optional two texts shown at the low and high end",
    ),
    r"""slider = slider(
  label: "Confidence",
  min: 0,
  max: 10,
  step: 1,
  labels: ["Low", "High"],
)
""",
    validate_slider,
)
