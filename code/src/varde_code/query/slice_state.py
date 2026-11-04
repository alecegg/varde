"""Read the derived-slice ledger without mutating the code index."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Never

from .modes import register_mode
from .params import QueryError


def _raise_missing_repo_root() -> Never:
    raise QueryError("invalid_input", 'missing string field "repoRoot"')


def slice_state(input: dict[str, Any]) -> dict[str, Any]:
    from varde_code.index.slice import dump_state

    path_value = input.get("dbPath")
    root_value = input.get("repoRoot")
    if not isinstance(path_value, str) and not isinstance(root_value, str):
        raise QueryError("invalid_input", 'missing string field "dbPath"')
    try:
        if isinstance(path_value, str):
            result = dump_state(db_path=Path(path_value))
        elif isinstance(root_value, str):
            result = dump_state(Path(root_value))
        else:
            _raise_missing_repo_root()
        if result.get("max_rev") == 0 and result.get("next_rev") == 1:
            result["next_rev"] = 0
        result["db_path"] = str(result["db_path"]).replace("/repos-py/", "/repos/", 1)
    except Exception as exc:
        raise QueryError("db_error", str(exc)) from exc
    else:
        return result


register_mode("slice_state", slice_state)
