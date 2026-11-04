"""Replay the interim toz shim cases using the frozen core mapping."""

import sqlite3
import sys
from pathlib import Path

from varde_core.paths import data_dir, varde_config_dir
from varde_core.redact import RedactConfig, Redactor, SecretValue
from varde_core.sqlite import configure_connection


def test_redact_builtin_user_and_literal_values() -> None:
    values = [SecretValue("TOKEN", "verysecret")]
    result = Redactor(RedactConfig(patterns=["verysecret"], values=values)).redact(
        "key=AKIA1234567890ABCDEF token=verysecret"
    )
    assert "[redacted:aws-key]" in result.text
    assert "[redacted:user]" in result.text
    assert result.notices[0].label == "aws-key"


def test_redact_configuration_and_invalid_pattern() -> None:
    assert Redactor(RedactConfig(builtin=False)).redact("secret").text == "secret"
    try:
        Redactor(RedactConfig(patterns=["("]))
    except ValueError as exc:
        assert "invalid redact pattern" in str(exc)
    else:
        raise AssertionError("invalid pattern was accepted")


def test_paths(monkeypatch) -> None:
    # The shim accepted a platform override; emulate its Linux case on every host.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("VARDE_CONFIG_DIR", "/chosen")
    assert varde_config_dir().as_posix() == "/chosen"
    monkeypatch.delenv("VARDE_CONFIG_DIR")
    monkeypatch.setenv("XDG_DATA_HOME", "/data")
    assert data_dir() == Path("/data")


def test_sqlite_helpers() -> None:
    connection = sqlite3.connect(":memory:")
    configure_connection(connection)
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert connection.execute("PRAGMA synchronous").fetchone() == (1,)
