"""Import every wave-1 Python name marked available in API.md."""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "core" / "API.md"


def test_api_available_names_import() -> None:
    text = API.read_text(encoding="utf-8")
    section = text.split("## Available imports", 1)[1].split("### Signatures fixed", 1)[
        0
    ]
    rows = re.findall(r"^\| `([\w.]+)` \| `([\w.]+)` \|", section, flags=re.MULTILINE)
    assert len(rows) > 50, f"API.md available-import rows dropped to {len(rows)}"
    for module_name, attribute in rows:
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute), f"{module_name}.{attribute} is absent"


def test_documented_callable_parameter_names() -> None:
    expected = {
        ("varde_core.envelope", "success"): ("data", "meta"),
        ("varde_core.envelope", "negative_result"): (
            "code",
            "message",
            "details",
            "meta",
        ),
        ("varde_core.envelope", "tool_error"): ("code", "message"),
        ("varde_core.jsonio", "dumps"): ("value",),
        ("varde_core.jsonio", "dumps_pretty"): ("value",),
        ("varde_core.paths", "varde_config_dir"): (),
        ("varde_core.paths", "data_dir"): (),
        ("varde_core.sqlite", "configure_connection"): ("connection",),
        ("varde_code.model", "span_of"): ("node",),
        ("varde_code.graph_model", "Graph"): ("paths", "out", "inc"),
        ("varde_code.graph_model", "Graph.to_dict"): ("self",),
        ("varde_code.graph_model", "Graph.from_dict"): ("value",),
    }
    graph_model = importlib.import_module("varde_code.graph_model")
    for (module_name, attribute), parameters in expected.items():
        target = (
            getattr(graph_model.Graph, attribute.removeprefix("Graph."))
            if attribute.startswith("Graph.")
            else getattr(importlib.import_module(module_name), attribute)
        )
        assert tuple(inspect.signature(target).parameters) == parameters, (
            f"{module_name}.{attribute} signature changed"
        )


def test_graph_contract_row_is_importable() -> None:
    graph_model = importlib.import_module("varde_code.graph_model")
    assert inspect.isclass(graph_model.Graph)
