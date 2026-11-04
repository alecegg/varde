from __future__ import annotations

import json
from pathlib import Path

from varde_code.query import dispatch


def test_find_pattern_single_file_infers_language_and_shapes_match(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.ts"
    source.write_text("foo(1);\nfoo(2);\n", encoding="utf-8")

    result = dispatch("find_pattern", {"filePath": str(source), "pattern": "foo($A)"})

    assert result["ok"] is True
    assert [match["text"] for match in result["data"]["matches"]] == [
        "foo(1)",
        "foo(2)",
    ]
    assert all(match["file"] == str(source) for match in result["data"]["matches"])
    assert result["data"]["matches"][0]["span"]["start_line"] == 1
    assert result["data"]["matches"][0]["captures"] == {"A": {"text": "1"}}


def test_find_pattern_passes_truncated_matches_to_output_capture(
    tmp_path: Path,
) -> None:
    source = tmp_path / "many.ts"
    source.write_text(
        "\n".join(f"foo({index});" for index in range(3)), encoding="utf-8"
    )

    class Capture:
        def __init__(self):
            self.rows = None

        def capture(self, input, source, label):
            self.rows = input
            return json.dumps({"handle": "captured"})

    capture = Capture()
    result = dispatch(
        "find_pattern",
        {
            "filePath": str(source),
            "pattern": "foo($A)",
            "matchesLimit": 1,
        },
        capture=capture,
    )

    assert result["data"]["guide"]["toz"]["handle"] == "captured"
    assert capture.rows is not None


def test_find_pattern_directory_requires_language_and_pages_matches(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.ts").write_text("foo(1);\nfoo(2);\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("foo(3);\n", encoding="utf-8")

    missing_language = dispatch(
        "find_pattern", {"path": str(tmp_path), "pattern": "foo($A)"}
    )
    assert missing_language["data"]["error"]["code"] == "invalid_input"

    result = dispatch(
        "find_pattern",
        {
            "path": str(tmp_path),
            "pattern": "foo($A)",
            "language": "ts",
            "matchesLimit": 1,
            "matchesOffset": 1,
        },
    )
    assert [match["text"] for match in result["data"]["matches"]] == ["foo(2)"]
    assert result["data"]["guide"]["truncated"]["matches"]["total"] == 3
    assert result["data"]["guide"]["truncated"]["matches"]["next_offset"] == 2


def test_find_pattern_invalid_target_and_options_are_tool_errors(
    tmp_path: Path,
) -> None:
    missing = dispatch("find_pattern", {"pattern": "foo()"})
    assert missing["data"]["error"]["code"] == "invalid_input"

    source = tmp_path / "main.ts"
    source.write_text("foo();", encoding="utf-8")
    invalid_limit = dispatch(
        "find_pattern",
        {
            "file": str(source),
            "pattern": "foo()",
            "matchesLimit": 0,
        },
    )
    assert invalid_limit["data"]["error"]["code"] == "invalid_input"


def test_find_pattern_rejects_unknown_input_key(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    source.write_text("foo();", encoding="utf-8")

    result = dispatch(
        "find_pattern",
        {"repoRoot": str(tmp_path), "language": "ts", "paths": "x", "pattern": "foo()"},
    )

    assert result["data"]["error"]["code"] == "invalid_input"
    assert "paths" in result["data"]["error"]["message"]
