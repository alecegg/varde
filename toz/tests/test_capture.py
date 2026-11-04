from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from varde_toz.capture import (
    CaptureInput,
    capture,
    capture_spooled,
)
from varde_toz.commands.capture import main as capture_command
from varde_toz.store import Store


def test_threshold_passes_through(tmp_path: Path) -> None:
    result = capture(
        CaptureInput(b"small", source="sample", threshold=5),
        Path.cwd(),
        tmp_path / "never-used.db",
    )
    status, output = result.status, result.output
    assert status == 0
    assert output == "small"


def test_capture_stores_and_returns_preview(tmp_path: Path) -> None:
    result = capture(
        CaptureInput(b"first\nsecond\n", label="sample", source="sample", force=True),
        tmp_path,
        tmp_path / "toz.db",
    )
    status, output = result.status, result.output
    assert status == 1
    assert "captured 13 bytes" in output
    assert "first" in output


def test_capture_preview_collapses_repeated_stderr_blocks(tmp_path: Path) -> None:
    stderr = b"error: boom\n  at main\n\n" * 3
    result = capture(
        CaptureInput(b"", stderr, label="sample", source="sample", force=True),
        tmp_path,
        tmp_path / "toz.db",
    )
    status, output = result.status, result.output
    assert status == 1
    assert "error: boom\n  at main ×3" in output


def test_spooled_stderr_preview_collapses_repeated_lines(tmp_path: Path) -> None:
    data = b"warning: repeated\nwarning: repeated\n"
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(data)
        stream.seek(0)
        status, output = capture_spooled(
            stream,
            len(data),
            CaptureInput(b"", source="streamed-stderr", force=True),
            tmp_path,
            stream_name="stderr",
            store_path=tmp_path / "toz.db",
        )
    assert status == 1
    assert "warning: repeated ×2" in output


def test_spooled_capture_redacts_values_across_ingest_blocks(tmp_path: Path) -> None:
    token = b"ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    pem = (
        b"-----BEGIN PRIVATE KEY-----\n"
        + (b"private-key-material\n" * 2_000)
        + b"-----END PRIVATE KEY-----\n"
    )
    data = (b"x" * 20_000 + b"\n") * 3 + pem + token + b"\n"
    db = tmp_path / "toz.db"
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(data)
        stream.seek(0)
        status, output = capture_spooled(
            stream,
            len(data),
            CaptureInput(b"", source="large", force=True),
            tmp_path,
            store_path=db,
        )
    assert status == 1
    assert "streamed text" in output
    handle = output.split("handle ", 1)[1].split()[0]
    with Store(db, readonly=True) as store:
        row = store.get_by_handle(handle)
        text = "\n".join(chunk["body"] for chunk in store.chunks_for(row["id"]))
    assert "[redacted:github]" in text
    assert "[redacted:pem]" in text
    assert "private-key-material" not in text
    assert b"ghp_" not in text.encode()


def test_spooled_stderr_preview_counts_lines_and_collapses_signatures(
    tmp_path: Path,
) -> None:
    pattern = (
        b"warning: streamed warning\nordinary stderr line\n"
        b"error: streamed failure marker\n"
    )
    data = pattern * 1_000
    assert len(data) == 78_000
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(data)
        stream.seek(0)
        status, output = capture_spooled(
            stream,
            len(data),
            CaptureInput(b"", source="streamed-stderr", force=True),
            tmp_path,
            stream_name="stderr",
            store_path=tmp_path / "toz.db",
        )
    assert status == 1
    assert "── stderr (3000 lines) ────────────────────────────────" in output
    assert (
        "warning: streamed warning\nordinary stderr line\n"
        "error: streamed failure marker\n" in output
    )


def test_spooled_capture_rejects_overlong_line_without_storing(tmp_path: Path) -> None:
    data = b"x" * (1024 * 1024 + 1)
    db = tmp_path / "toz.db"
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(data)
        stream.seek(0)
        try:
            capture_spooled(
                stream,
                len(data),
                CaptureInput(b"", source="large", force=True),
                tmp_path,
                store_path=db,
            )
        except ValueError as error:
            assert "line exceeds 1 MiB" in str(error)
        else:
            raise AssertionError("overlong line was accepted")
    stored = 0
    if db.exists():
        with Store(db, readonly=True) as store:
            stored = store.conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    assert stored == 0


def test_capture_command_routes_large_stdin_through_spool(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    data = (b"large line content " * 800 + b"\n") * 70
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(data)
        stream.seek(0)

        class Input:
            buffer = stream

        monkeypatch.setattr(sys, "stdin", Input())
        monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "toz"))
        monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
        code = capture_command(
            ["--force", "--project", str(tmp_path), "--source", "large-input"]
        )
    output = capsys.readouterr().out
    assert code == 0
    assert "streamed text; fixed-size sections" in output
    assert list((tmp_path / "toz").rglob("toz.db"))


def test_capture_uses_redaction_config_for_text_and_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[redact]\nbuiltin=false\npatterns=["private-value", "alice", "password123"]\n'
        'dotenv=["custom.env"]\n'
    )
    (tmp_path / "custom.env").write_text("DB_PASSWORD=password123\n")
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("TOZ_CONFIG_DIR", raising=False)
    db = tmp_path / "toz.db"
    result = capture(
        CaptureInput(
            b"private-value password123 ghp_abcdefghijklmnopqrstuvwxyz0123456789\n",
            label="private-value",
            source="https://alice:password123@example.test/?token=private-value",
            force=True,
        ),
        tmp_path,
        db,
    )
    status, output = result.status, result.output
    assert status == 1
    handle = output.split("handle ", 1)[1].split()[0]
    with Store(db, readonly=True) as store:
        row = store.get_by_handle(handle)
        body = store.full_text(row["id"])
    assert "private-value" not in body
    assert "password123" not in body
    assert "ghp_" in body
    assert "private-value" not in row["label"]
    assert "alice" not in row["source"]
    assert "password123" not in row["source"]


def test_configured_never_capture_rule_skips_storage(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[capture]\nbuiltin_never=false\nnever=["blocked*"]\n'
    )
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("TOZ_CONFIG_DIR", raising=False)
    db = tmp_path / "toz.db"
    result = capture(
        CaptureInput(b"large output\n", source="blocked command", force=True),
        tmp_path,
        db,
    )
    status, output = result.status, result.output
    assert status == 0
    assert output == "large output\n"
    assert not db.exists()
