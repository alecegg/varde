from __future__ import annotations

import json
from pathlib import Path

from varde_toz.capture import CaptureInput, capture
from varde_toz.chunk import truncate_middle
from varde_toz.store import Store
from varde_toz.strategies import (
    Strategy,
    detect,
)

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


def test_toz_core_fixtures_select_content_strategies() -> None:
    cases = (
        ("cargo-test-failures.txt", Strategy.TEST),
        ("git-diff.patch", Strategy.DIFF),
        ("htmd-readme.md", Strategy.MARKDOWN),
        ("macos-syslog.log", Strategy.LOG),
    )
    for fixture, expected in cases:
        text = (FIXTURES / fixture).read_text()
        assert detect(text) == expected


def test_minified_cargo_metadata_capture_expands_to_searchable_json(
    tmp_path: Path,
) -> None:
    raw = (FIXTURES / "cargo-metadata.json").read_text()
    assert len(raw.splitlines()) == 1
    result = capture(
        CaptureInput(
            raw.encode(), label="cargo-metadata", source="cargo metadata", force=True
        ),
        tmp_path,
        tmp_path / "toz.db",
    )
    status, output = result.status, result.output
    assert status == 1
    handle = output.split("handle ", 1)[1].split()[0]
    with Store(tmp_path / "toz.db", readonly=True) as store:
        row = store.get_by_handle(handle)
        text = store.full_text(row["id"])
        assert detect(text) == Strategy.JSON
        assert json.loads(text) == json.loads(raw)
        assert text.startswith('{\n  "')
        assert store.search("build_directory")


def test_title_truncation_preserves_both_ends() -> None:
    title = "Guide > Development > Web application frameworks (3/9)"
    assert len(truncate_middle(title, 30)) == 30
    assert truncate_middle(title, 30).startswith("Guide > ")
    assert truncate_middle(title, 30).endswith("orks (3/9)")
