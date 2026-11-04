import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from varde_core.constants import (
    LEARN_NOTE,
    TOZ_BLOCK_END,
    TOZ_BLOCK_START,
    TOZ_NOTE,
    toz_instruction_block,
)
from varde_core.envelope import ENVELOPE_VERSION, negative_result, success, tool_error
from varde_core.jsonio import dumps, dumps_pretty
from varde_core.paths import data_dir, varde_config_dir
from varde_core.sqlite import configure_connection


def test_envelopes_have_stable_key_order_and_shapes() -> None:
    assert ENVELOPE_VERSION == 1
    assert list(success({"x": 1}, {})) == [
        "schema_version",
        "envelope_version",
        "ok",
        "outcome",
        "data",
        "meta",
    ]
    assert success({"x": 1}, {}) == {
        "schema_version": 1,
        "envelope_version": 1,
        "ok": True,
        "outcome": "success",
        "data": {"x": 1},
        "meta": {},
    }
    result = cast("dict[str, Any]", negative_result("bad", "no", [1], {}))
    assert result["data"]["error"] == {
        "code": "bad",
        "message": "no",
        "details": [1],
    }
    assert tool_error("bad", "no")["meta"] == {"truncated": False}


def test_paths_follow_environment_and_platform_rules(monkeypatch) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", "/chosen")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
    assert varde_config_dir() == Path("/chosen")
    monkeypatch.delenv("VARDE_CONFIG_DIR")
    assert varde_config_dir() == Path("/xdg/config/varde")
    monkeypatch.setattr("varde_core.paths.os.sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    monkeypatch.setenv("HOME", "/home/test")
    assert data_dir() == Path("/home/test/.local/share")
    monkeypatch.setenv("XDG_DATA_HOME", "/data")
    assert data_dir() == Path("/data")
    monkeypatch.setattr("varde_core.paths.os.sys.platform", "darwin")
    assert data_dir() == Path("/home/test/Library/Application Support")


def test_sqlite_pragmas_match_rust_configuration() -> None:
    connection = sqlite3.connect(":memory:")
    configure_connection(connection)
    assert connection.execute("PRAGMA busy_timeout").fetchone() == (30000,)
    assert connection.execute("PRAGMA journal_mode").fetchone() == ("memory",)
    assert connection.execute("PRAGMA synchronous").fetchone() == (1,)
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_jsonio_matches_json_shape_unicode_and_float_style() -> None:
    value = {"name": "ø", "number": 1.0, "tiny": 1e-7, "items": [True, None]}
    assert dumps(value) == '{"name":"ø","number":1.0,"tiny":1e-7,"items":[true,null]}'
    assert dumps_pretty(value) == (
        '{\n  "name": "ø",\n  "number": 1.0,\n  "tiny": 1e-7,\n'
        '  "items": [\n    true,\n    null\n  ]\n}'
    )
    assert dumps([1e16, 1e21, 1.2345678901234568e17, 1e-5, 1.7976931348623157e308]) == (
        "[1e16,1e21,1.2345678901234568e17,0.00001,1.7976931348623157e308]"
    )


def test_constants_and_instruction_block() -> None:
    template = (
        f"head\n{TOZ_BLOCK_START}\n## Title\n\n"
        f"{{{{TOZ_SHARED_NOTE}}}}\n{TOZ_BLOCK_END}\ntail"
    )
    assert toz_instruction_block(template) == f"## Title\n\n{TOZ_NOTE}"
    # varde instructions embeds this exact shared note in the learn block.
    assert LEARN_NOTE == (
        "Record friction as it happens with `varde learn friction add`. "
        "Record each user correction with the user's stated reason. "
        "Do not record predicted risks."
    )


def test_hook_modules_load_without_sqlite3_or_json() -> None:
    # API.md app-shell startup-budget task: the hook path imports these modules
    # without loading sqlite3 or json.
    modules = (
        "varde_core.envelope",
        "varde_core.paths",
        "varde_core.sqlite",
        "varde_core.constants",
    )
    for module_name in modules:
        code = (
            "import sys\n"
            f"import {module_name}\n"
            "print(sorted({'sqlite3', 'json'} & set(sys.modules)))\n"
        )
        result = subprocess.run(  # noqa: S603 - Test runs a controlled interpreter command to inspect module imports.
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            env={"PATH": str(Path(sys.executable).parent), "HOME": str(Path.home())},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "[]", f"{module_name} loaded {result.stdout}"
