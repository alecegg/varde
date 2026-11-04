"""Component `deps`: a task dependency graph; props are the edges."""

from varde_learn.docs.pages.blocks.rules import Fault, check_keys
from varde_learn.docs.pages.blocks.spec import BlockSpec

_FORBIDDEN = (":", ",", "\n", "#")


def _name_fault(name: object, where: str) -> list[Fault]:
    if (
        isinstance(name, str)
        and name.strip()
        and not any(c in name for c in _FORBIDDEN)
    ):
        return []
    return [Fault("type", f"{where}: names must be text without ':', ',' or '#'")]


def validate_deps(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"edges"}, set(), "deps")
    edges = data.get("edges")
    if "edges" not in data:
        return faults
    if not isinstance(edges, dict):
        return faults + [Fault("type", "deps.edges must be a table of lists")]
    for task, needs in edges.items():
        faults += _name_fault(task, "deps.edges")
        if not isinstance(needs, list):
            faults.append(Fault("type", f"deps.edges.{task} must be a list of tasks"))
            continue
        for need in needs:
            faults += _name_fault(need, f"deps.edges.{task}")
    return faults


DEPS = BlockSpec(
    "deps",
    "A task dependency graph drawn from edges",
    ("edges  table mapping each task id to the list of tasks it depends on",),
    r"""deps = deps(
  edges: {"a": [], "b": ["a"], "c": ["a", "b"]},
)
""",
    validate_deps,
)
