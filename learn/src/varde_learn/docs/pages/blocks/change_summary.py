"""Block type for the generated change line: counts the page's change markers.

`summarize` and `sentence` are pure. Markers are read from parsed statement props
(`collect_markers`), never from rendered HTML.
"""

from collections.abc import Iterable, Mapping

from varde_learn.docs.pages.blocks.change import CHANGES
from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

Marker = tuple[str, str]  # (kind, change)
KINDS = {
    "file": ("file", "files"),
    "endpoint": ("endpoint", "endpoints"),
    "parameter": ("parameter", "parameters"),
    "response": ("response", "responses"),
    "entity": ("entity", "entities"),
    "field": ("field", "fields"),
}
VERBS = {
    "added": "added",
    "modified": "changed",
    "removed": "removed",
    "renamed": "renamed",
}
EMPTY = "No changes marked on this page."
UNCOUNTED = "Change counts appear when the page is rendered."


def _marker(kind: str, item: object) -> list[Marker]:
    change = item.get("change") if isinstance(item, Mapping) else None
    return [(kind, change)] if change in CHANGES else []


def _typed_map(kind: str, value: object) -> list[Marker]:
    items = value.values() if isinstance(value, Mapping) else []
    return [m for item in items for m in _marker(kind, item)]


def _tables(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def markers_of(component: str, props: Mapping[str, object]) -> list[Marker]:
    """The change markers of one statement's props; invalid shapes give none."""
    if component == "file-tree":
        return [m for e in _tables(props.get("entries")) for m in _marker("file", e)]
    if component == "data-model":
        found: list[Marker] = []
        for entity in _tables(props.get("entity")):
            found += _marker("entity", entity)
            fields = entity.get("fields") if isinstance(entity, Mapping) else None
            found += _typed_map("field", fields)
        return found
    if component == "endpoint":
        found = _marker("endpoint", props) + _typed_map(
            "parameter", props.get("request")
        )
        return found + [
            m for r in _tables(props.get("responses")) for m in _marker("response", r)
        ]
    return []


def collect_markers(
    statements: Iterable[tuple[str, Mapping[str, object]]],
) -> list[Marker]:
    """Markers of every `(component, props)` pair, in page order."""
    return [m for component, props in statements for m in markers_of(component, props)]


def summarize(markers: Iterable[Marker]) -> list[tuple[str, int]]:
    """`(phrase, count)` pairs: kind order, then change order."""
    found = list(markers)
    result: list[tuple[str, int]] = []
    for kind, (singular, plural) in KINDS.items():
        for change in CHANGES:
            count = found.count((kind, change))
            if count:
                result.append(
                    (
                        f"{count} {singular if count == 1 else plural} {VERBS[change]}",
                        count,
                    )
                )
    return result


def sentence(markers: Iterable[Marker]) -> str:
    phrases = [phrase for phrase, _ in summarize(markers)]
    return ", ".join(phrases) if phrases else EMPTY


def validate_change_summary(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, set(), {"title"}, "change-summary")
    return faults + str_field(data, "title", "change-summary")


CHANGE_SUMMARY = BlockSpec(
    "change-summary",
    "One generated line counting the change markers on the page",
    (
        "title  optional short heading",
        "No other field: the line counts the `change` markers of data-model,",
        "endpoint and file-tree blocks on the same page, for example",
        "'2 files added, 1 endpoint changed, 1 field removed'. A page without",
        "markers shows 'No changes marked on this page.'",
    ),
    r"""change-summary = change-summary(
  title: "What changed",
)
""",
    validate_change_summary,
)
