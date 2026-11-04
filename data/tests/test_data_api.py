"""Keep the documented data API importable and its lock paths explicit."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "API.md"


def test_documented_public_names_exist() -> None:
    text = API.read_text(encoding="utf-8")
    rows = re.findall(r"`(varde_data(?:\.[\w]+)?)` exposes ([^\n]+)", text)
    assert rows
    for module_name, names in rows:
        module = importlib.import_module(module_name)
        for name in re.findall(r"`([A-Za-z_]\w*)", names):
            assert hasattr(module, name), f"{module_name}.{name} is absent"


def test_documented_errors_exist_at_package_root() -> None:
    package = importlib.import_module("varde_data")
    for name in ("DataError", "NotFound", "Invalid", "Conflict", "Locked"):
        assert hasattr(package, name), f"varde_data.{name} is absent"


def test_established_lock_paths_are_documented() -> None:
    text = API.read_text(encoding="utf-8")
    for path in (
        "friction.jsonl",
        ".<reader>.lock",
        "relay/.lock",
        "Per-address directory",
        ".queue-order.json.lock",
        ".cache/inbox/.messages.lock",
        ".cache/inbox/.state.lock",
        ".cache/inbox/.events.lock",
        ".cache/inbox/slots/.lock",
    ):
        assert path in text


def test_messages_api_documents_read_and_cursor_semantics() -> None:
    text = API.read_text(encoding="utf-8")
    for phrase in (
        "MessageRepository",
        "read_since",
        "opaque ordered `Cursor`",
        "do not lock or write",
        "first-contact reader starts at",
        "reader resolved from each message's recipient address",
    ):
        assert phrase in text
