from __future__ import annotations

import json

import pytest
from varde_code.query import dispatch, modes, register_mode, run_mode
from varde_code.query.noise_filter import (
    is_frontend_asset_path,
    is_generated_or_vendored_path,
    is_minified_source,
    is_non_source_path,
    is_scaffold_template_path,
)
from varde_code.query.output import paginate
from varde_code.query.params import QueryError, nonnegative_int, req_str


@pytest.fixture(autouse=True)
def isolate_test_modes():
    original = modes._HANDLERS.copy()
    yield
    modes._HANDLERS.clear()
    modes._HANDLERS.update(original)


def test_mode_registration_and_dispatch() -> None:
    register_mode("test_echo", lambda value: {"value": value["value"]})
    result = dispatch("test_echo", {"value": "héllo"})
    assert result["ok"] is True
    assert result["data"] == {"value": "héllo"}
    assert json.loads(run_mode("test_echo", '{"value":1}'))["data"] == {"value": 1}


def test_unknown_mode_and_invalid_json_are_tool_errors() -> None:
    assert dispatch("missing_mode", {})["data"]["error"]["code"] == "unknown_mode"
    result = json.loads(run_mode("test_echo", "{"))
    assert result["data"]["error"]["code"] == "invalid_input"
    assert result["outcome"] == "tool-error"


def test_batch_keeps_per_call_failures_and_inherits_repo_context() -> None:
    register_mode("test_context", lambda value: {"root": value.get("repoRoot")})
    result = dispatch(
        "batch",
        {
            "repoRoot": "/repo",
            "calls": [
                {"mode": "test_context"},
                {"mode": "missing_mode"},
                {"mode": "batch"},
            ],
        },
    )
    assert result["ok"] is True
    assert result["data"][0]["data"] == {"root": "/repo"}
    assert result["data"][1]["data"]["error"]["code"] == "unknown_mode"
    assert result["data"][2]["data"]["error"]["code"] == "invalid_input"


def test_pagination_window_and_symbols_by_file() -> None:
    result, meta = paginate(
        [1, 2, 3, 4], {"resultsLimit": 2, "resultsOffset": 1}, "items"
    )
    assert result == [2, 3]
    assert meta == {
        "shown": 2,
        "total": 4,
        "offset": 1,
        "limit": 2,
        "next_offset": 3,
        "request": "set resultsOffset to next_offset, or set fullResults to true",
    }
    files = {"a.py": [1, 2], "b.py": [3, 4]}
    result, meta = paginate(
        files, {"resultsLimit": 2, "resultsOffset": 1}, "symbols_in_files"
    )
    assert result == {"a.py": [2], "b.py": [3]}
    assert meta is not None
    assert meta["total"] == 4


def test_toz_capture_attaches_handle_and_retrieval_guides() -> None:
    class Capture:
        def capture(self, input, source, label):
            return json.dumps({"handle": "H123", "toc": []})

    register_mode("test_list", lambda _value: list(range(4)))
    result = dispatch("test_list", {"resultsLimit": 2}, Capture())
    assert result["meta"]["toz"] is not None
    assert result["meta"]["toz"]["handle"] == "H123"
    assert (
        result["meta"]["pagination"]["results"]["toz_search"]
        == 'varde run query --handle H123 "<term>"'
    )


def test_invalid_pagination_and_params() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        paginate([1], {"resultsLimit": 0}, "items")
    with pytest.raises(QueryError, match="missing string"):
        req_str({}, "filePath")
    with pytest.raises(QueryError, match="nonnegative integer"):
        nonnegative_int({"limit": True}, "limit")


def test_noise_filter_matches_components_and_source_kinds() -> None:
    assert is_generated_or_vendored_path("src/node_modules/lib.js")
    assert not is_generated_or_vendored_path("src/distributor/main.rs")
    assert is_scaffold_template_path("generator/templates/app/main.py")
    assert not is_scaffold_template_path("src/template_engine.py")
    assert is_frontend_asset_path("assets/js/app.js")
    assert not is_frontend_asset_path("assets/python/app.py")
    assert is_non_source_path("README.md")
    assert is_minified_source("x" * 2100)
    assert not is_minified_source("x" * 2100 + "\nshort\nshort")


def test_compact_keeps_a_root_relative_path_whatever_the_cwd(tmp_path, monkeypatch):
    """A repo dir named like its package dir must not lose that package prefix."""
    from varde_code.query.output import compact

    root = tmp_path / "pkg"
    (root / "pkg").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    data = {"files": [{"path": "pkg/a.py"}, {"path": str(root / "pkg" / "b.py")}]}

    compact(data, {"repoRoot": str(root)})

    assert [item["path"] for item in data["files"]] == ["pkg/a.py", "pkg/b.py"]
