from __future__ import annotations

from pathlib import Path

import pytest
from varde_toz.capture import CaptureInput, capture
from varde_toz.redact_toz import configured_redactor, redact_configured
from varde_toz.store import Store

FIXTURES = Path(__file__).parent / "fixtures/toz-core"
REDACTION_FIXTURES = sorted(
    path
    for path in FIXTURES.iterdir()
    if path.is_file() and path.suffix in {".txt", ".log", ".md", ".patch", ".pem"}
)


def _capture_reused(text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Capture text that the hook already redacted and return the stored text."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config_dir))
    db = tmp_path / "reused.db"
    capture(
        CaptureInput(
            text.encode(),
            label="fixture",
            source="cat README.md",
            kind="hook:Bash",
            force=True,
            content_redacted=True,
        ),
        root=tmp_path,
        store_path=db,
    )
    with Store.open_readonly(db) as store:
        row = store.list(1, False)[0]
        return store.full_text(row["id"])


@pytest.mark.parametrize("fixture", REDACTION_FIXTURES)
def test_reused_redaction_stores_fixture_text_unchanged(
    fixture: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = fixture.read_text(errors="replace")
    # The toz-core fixtures carry no secret-like values, so redaction is a no-op
    # and the reuse path must store the text as given.
    assert redact_configured(text, configured_redactor(tmp_path)) == (text, 0)
    expected = text.removesuffix("\n")
    assert _capture_reused(text, tmp_path, monkeypatch) == expected


@pytest.mark.parametrize("size", [4 * 1024, 16 * 1024])
def test_reused_redaction_stores_generated_body_unchanged(
    size: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = ("ordinary output line\n" * (size // 21 + 1))[:size]
    assert _capture_reused(body, tmp_path, monkeypatch) == body


def test_custom_rule_matching_replacement_text_is_not_idempotent() -> None:
    text = "ghp_" + "a" * 36
    config = {
        "builtin": True,
        "patterns": [r"\[redacted:github\]"],
        "values": {},
        "reveal": 2,
    }
    once, _notices = redact_configured(text, config)
    twice, _count = redact_configured(once, config)
    assert once != twice


def test_builtin_redaction_replacement_is_idempotent() -> None:
    config = {"builtin": True, "patterns": [], "values": {}, "reveal": 2}
    once, notices = redact_configured("ghp_" + "a" * 36, config)
    twice, count = redact_configured(once, config)
    assert notices
    assert (twice, count) == (once, 0)


@pytest.mark.parametrize("reuse", [False, True])
def test_capture_redacts_builtin_secret_split_by_ansi_even_when_reuse_requested(
    reuse: bool, tmp_path: Path
) -> None:
    body = ("line\n" * 3000 + "key AKIA\x1b[0mABCDEFGHIJKLMNOP").encode()
    db = tmp_path / f"ansi-{reuse}.db"
    capture(
        CaptureInput(
            body,
            label="ansi",
            source="fixture",
            kind="hook:Bash",
            force=True,
            content_redacted=reuse,
        ),
        root=tmp_path,
        store_path=db,
    )
    with Store.open_readonly(db) as store:
        row = store.list(1, False)[0]
        stored = "\n".join(chunk["body"] for chunk in store.chunks_for(row["id"]))
    assert "ABCDEFGHIJKLMNOP" not in stored
    assert "[redacted:aws-key]" in stored
