import subprocess
import sys
import time
from pathlib import Path

import pytest
from varde_core.redact import (
    Kind,
    Notice,
    RedactConfig,
    Redactor,
    SecretValue,
    Span,
    values,
)


def _values(*pairs: tuple[str, str]) -> list[SecretValue]:
    return [SecretValue(name, value) for name, value in pairs]


def test_redaction_records_keep_value_semantics() -> None:
    secret = SecretValue("TOKEN", "secret")
    assert secret == SecretValue(name="TOKEN", value="secret")
    assert secret != ("TOKEN", "secret")
    assert hash(secret) == hash(SecretValue("TOKEN", "secret"))

    config = RedactConfig(False, ["secret"], [secret], 0)
    assert config == RedactConfig(
        builtin=False, patterns=["secret"], values=[secret], reveal=0
    )
    assert RedactConfig().patterns == ()
    assert RedactConfig().values == ()
    assert RedactConfig().reveal == 2
    with pytest.raises(AttributeError):
        secret.name = "OTHER"  # type: ignore[misc]


def test_redaction_import_avoids_reflection_modules_and_loads_values_lazily() -> None:
    # API.md freezes varde_core.redact.values; the app-shell startup-budget task
    # requires the hook import path to stay light, so values load on first use.
    code = """import sys
import varde_core.redact as redact
assert not {
    'dataclasses', 'inspect', 'typing', 'varde_core.redact.values'
} & sys.modules.keys()
assert redact.values.from_environment() == []
assert 'varde_core.redact.values' in sys.modules
"""
    result = subprocess.run(  # noqa: S603 - Test runs a controlled local command to verify redaction.
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(Path(sys.executable).parent), "HOME": str(Path.home())},
    )
    assert result.returncode == 0, result.stderr


def test_default_config_is_builtin_with_reveal_two() -> None:
    cfg = RedactConfig()
    assert cfg.builtin and cfg.reveal == 2
    assert cfg.patterns == () and cfg.values == ()


def test_every_builtin_pattern_redacts_with_its_kind() -> None:
    cases = [
        ("aws-key", "AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        (
            "aws-secret",
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "EXAMPLEKEY",
        ),
        (
            "github",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        ("github-pat", f"github_pat_{'a' * 82}", "github_pat_"),
        ("api-key", f"sk-proj-{'b' * 24}", "sk-proj-"),
        ("slack", "xoxb-1234567890", "xoxb-1234567890"),
        ("bearer", "Bearer abcdefghijklmnop", "abcdefghijklmnop"),
        (
            "pem",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----",
            "MIIB",
        ),
        ("env-assign", "DATABASE_PASSWORD=hunter2", "hunter2"),
        ("url-creds", "https://alice:s3cr3t@example.com", "s3cr3t"),
    ]
    for kind, secret, needle in cases:
        out = Redactor(RedactConfig()).redact(secret)
        assert f"[redacted:{kind}]" in out.text and needle not in out.text
        assert Notice(Kind.PATTERN, kind, 1) in out.notices


def test_env_redaction_preserves_blank_line_span() -> None:
    redactor = Redactor(RedactConfig())
    assert redactor.redact("before\n\nTOKEN=abcdefgh\nafter").text == (
        "before\n[redacted:env-assign]\nafter"
    )


@pytest.mark.parametrize("prefix", ["+", "-", "1+", "_a."])
def test_url_credentials_after_nonword_prefix(prefix: str) -> None:
    text = f"{prefix}https://u:p@h"
    assert "p@" not in Redactor(RedactConfig()).redact(text).text


@pytest.mark.parametrize("text", ["TOKEN=\nnext", "\u00a0TOKEN=abc", "\x0cTOKEN=abc"])
def test_env_assignment_preserves_whitespace_semantics(text: str) -> None:
    assert Redactor(RedactConfig()).redact(text).text == "[redacted:env-assign]"


def _fastest_redact(redactor: Redactor, text: str) -> float:
    best = float("inf")
    for _ in range(5):
        started = time.perf_counter()
        redactor.redact(text)
        best = min(best, time.perf_counter() - started)
    return best


def test_builtin_redaction_scales_on_adversarial_inputs() -> None:
    redactor = Redactor(RedactConfig())
    cases = (
        ("\n" * 1000, "\n" * 4000),
        ("a.b-c+d" * 1000, "a.b-c+d" * 4000),
        ("-----BEGIN PRIVATE KEY-----" * 100, "-----BEGIN PRIVATE KEY-----" * 400),
    )
    for small, large in cases:
        small_seconds = _fastest_redact(redactor, small)
        large_seconds = _fastest_redact(redactor, large)
        assert large_seconds < small_seconds * 8 + 0.05


def test_builtin_disabled_and_user_pattern() -> None:
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Synthetic token exercises redaction matching.
    disabled = Redactor(RedactConfig(builtin=False)).redact(token)
    assert disabled.text == token
    assert disabled.notices == []
    cfg = RedactConfig(builtin=False, patterns=["secret-[0-9]+"])
    user = Redactor(cfg).redact("a secret-42 b")
    assert user.text == "a [redacted:user] b"
    assert user.notices == [Notice(Kind.PATTERN, "user", 1)]


def test_invalid_pattern_names_pattern_and_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"\[unterminated"):
        Redactor(RedactConfig(patterns=["[unterminated"]))


def test_value_partial_reveal_boundaries_and_zero() -> None:
    cfg = RedactConfig(builtin=False, values=_values(("TOKEN", "supersecretvalue")))
    assert (
        Redactor(cfg).redact("token is supersecretvalue here").text
        == "token is su…ue[redacted:value:TOKEN] here"
    )
    for value, expected in [
        ("x" * 15, "[redacted:value:A]"),
        ("x" * 16, "xx…xx[redacted:value:A]"),
    ]:
        cfg = RedactConfig(builtin=False, values=_values(("A", value)))
        assert Redactor(cfg).redact(value).text == expected
    cfg = RedactConfig(
        builtin=False, reveal=0, values=_values(("A", "abcdefghijklmnopqrst"))
    )
    assert Redactor(cfg).redact("abcdefghijklmnopqrst").text == "[redacted:value:A]"
    cfg = RedactConfig(
        builtin=False, reveal=3, values=_values(("A", "abcdefghijklmnopqrst"))
    )
    assert (
        Redactor(cfg).redact("abcdefghijklmnopqrst").text == "abc…rst[redacted:value:A]"
    )


def test_overlaps_ties_spans_and_aggregation() -> None:
    cfg = RedactConfig(
        builtin=False, values=_values(("ABC", "abc"), ("ABCDEF", "abcdef"))
    )
    assert Redactor(cfg).redact("abcdef").text == "[redacted:value:ABCDEF]"
    cfg = RedactConfig(
        builtin=False, values=_values(("LATER", "bcde"), ("EARLY", "abcd"))
    )
    assert Redactor(cfg).redact("abcde").text == "[redacted:value:EARLY]"
    value = "abcdefghijk1234567890!QRSTUVWXYZ"
    cfg = RedactConfig(values=_values(("MY_TOKEN", value)))
    out = Redactor(cfg).redact(f"Authorization: Bearer {value}")
    assert out.text == "Authorization: [redacted:bearer]"
    assert out.notices == [Notice(Kind.PATTERN, "bearer", 1)]
    cfg = RedactConfig(builtin=False, patterns=["abc"], values=_values(("A", "abc")))
    assert Redactor(cfg).redact("abc").text == "[redacted:user]"


def test_literal_precedence_uses_utf8_byte_length() -> None:
    cfg = RedactConfig(
        builtin=False, values=_values(("ASCII", "abcd"), ("UNICODE", "ééé"))
    )
    assert Redactor(cfg).redact("ééé").text.endswith("[redacted:value:UNICODE]")


def test_span_order_rebuild_and_notices_hide_secrets() -> None:
    cfg = RedactConfig(
        builtin=False, patterns=["tok-[0-9]+"], values=_values(("KEY", "hunter2secret"))
    )
    text = "a tok-12 b hunter2secret c"
    engine = Redactor(cfg)
    spans = engine.redact_spans(text)
    assert (
        len(spans) == 2
        and spans[0].kind == Kind.PATTERN
        and spans[1].kind == Kind.VALUE
    )
    assert spans[0].end <= spans[1].start
    rebuilt, cursor = [], 0
    for span in spans:
        rebuilt.extend((text[cursor : span.start], span.replacement))
        cursor = span.end
    rebuilt.append(text[cursor:])
    assert "".join(rebuilt) == engine.redact(text).text
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Synthetic token exercises redaction matching.
    secret = "supersecretvalue"  # noqa: S105 - Synthetic secret exercises redaction matching.
    out = Redactor(RedactConfig(values=_values(("TOKEN", secret)))).redact(
        f"{token} and {token} and {secret}"
    )
    assert out.notices == [
        Notice(Kind.PATTERN, "github", 2),
        Notice(Kind.VALUE, "TOKEN", 1),
    ]
    assert token not in out.text and secret not in out.text


def test_no_matches_and_empty_input() -> None:
    engine = Redactor(RedactConfig())
    assert engine.redact("plain text\n").text == "plain text\n"
    assert engine.redact("plain text").notices == []
    assert engine.redact_spans("plain text") == []
    assert engine.redact("").text == ""


def test_spans_use_utf8_byte_offsets() -> None:
    engine = Redactor(RedactConfig(builtin=False, patterns=["secret"]))
    assert engine.redact_spans("é secret") == [
        Span(3, 9, "[redacted:user]", Kind.PATTERN)
    ]


def test_dotenv_vectors_and_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        (
            '# comment line\nPLAIN=plainvalue\nexport EXPORTED="exported value"\n'
            "SINGLE='singlequoted'\nSEVEN=abcdefg\nEIGHT=abcdefgh\nBOOL=true\n"
            "NUM=12345678\nEMPTY=\nNOEQUALS\nexport\tTABBED=tabbedvalue\n"
            "\tINDENTED=indentedvalue"
        ),
        encoding="utf-8",
    )
    assert values.from_dotenv(path) == _values(
        ("EIGHT", "abcdefgh"),
        ("EXPORTED", "exported value"),
        ("INDENTED", "indentedvalue"),
        ("PLAIN", "plainvalue"),
        ("SINGLE", "singlequoted"),
        ("TABBED", "tabbedvalue"),
    )
    path.write_text(
        (
            'UNQUOTED=abcdefghijk123 # prod key\nQUOTED="zyxwvutsrq987" # note\n'
            "SINGLE='singlequoted9' # note\nHASH=abcdefghijk123#notacomment\n"
            "TAB=abcdefghijk123\t# tabbed comment"
        ),
        encoding="utf-8",
    )
    assert values.from_dotenv(path) == _values(
        ("HASH", "abcdefghijk123#notacomment"),
        ("QUOTED", "zyxwvutsrq987"),
        ("SINGLE", "singlequoted9"),
        ("TAB", "abcdefghijk123"),
        ("UNQUOTED", "abcdefghijk123"),
    )
    path.write_text(
        "SPACED= # a long comment\nTABBED=\t# another comment", encoding="utf-8"
    )
    assert values.from_dotenv(path) == []
    assert values.from_dotenv(tmp_path / "absent.env") == []
    (tmp_path / "binary.env").write_bytes(b"\xff\xfe=x")
    assert values.from_dotenv(tmp_path / "binary.env") == []


def test_dotenv_collection_scope_sorting_and_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VARDE_TEST_COLLECT_TOKEN", "environmenttokenvalue")
    (tmp_path / ".env").write_text("TOKEN=envfiletokenvalue\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text(
        "TOKEN=localfiletokenvalue\nTOKEN=envfiletokenvalue\n", encoding="utf-8"
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".env").write_text("TOKEN=nestedtokenvalue\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("TOKEN=notadotenvfile\n", encoding="utf-8")
    collected = values.collect(tmp_path)
    named = [
        item for item in collected if item.name in {"TOKEN", "VARDE_TEST_COLLECT_TOKEN"}
    ]
    assert named == [
        SecretValue("TOKEN", "envfiletokenvalue"),
        SecretValue("TOKEN", "localfiletokenvalue"),
        SecretValue("VARDE_TEST_COLLECT_TOKEN", "environmenttokenvalue"),
    ]
    assert all(
        item.value not in {"nestedtokenvalue", "notadotenvfile"} for item in collected
    )


def test_environment_filters_secret_names_short_values_and_common_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VARDE_TEST_REDACT_TOKEN", "environmenttokenvalue")
    monkeypatch.setenv("varde_test_redact_lowercase_password", "lowercasepassword")
    monkeypatch.setenv("VARDE_TEST_REDACT_KEY", "abcdefg")
    monkeypatch.setenv("VARDE_TEST_REDACT_SECRET", "12345678")
    monkeypatch.setenv("VARDE_TEST_REDACT_CREDENTIAL", "true")
    monkeypatch.setenv("VARDE_TEST_REDACT_PLAIN", "plainnotsecret")
    found = values.from_environment()
    assert SecretValue("VARDE_TEST_REDACT_TOKEN", "environmenttokenvalue") in found
    assert (
        SecretValue("varde_test_redact_lowercase_password", "lowercasepassword")
        in found
    )
    assert sum("VARDE_TEST_REDACT" in item.name.upper() for item in found) == 2


def test_environment_skips_surrogate_escaped_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        values.os, "environ", {"VARDE_TEST_PASSWORD": "secret\udcffvalue"}
    )
    assert values.from_environment() == []


def test_environment_filters_common_numeric_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VARDE_TEST_NUMERIC_SECRET_UNDERSCORE", "1_000_000")
    monkeypatch.setenv("VARDE_TEST_NUMERIC_SECRET_SPACES", " 10000000 ")
    monkeypatch.setenv("VARDE_TEST_NUMERIC_SECRET_NUMBER", "10000000")

    found = values.from_environment()

    assert SecretValue("VARDE_TEST_NUMERIC_SECRET_UNDERSCORE", "1_000_000") in found
    assert SecretValue("VARDE_TEST_NUMERIC_SECRET_SPACES", " 10000000 ") in found
    assert not any(item.name == "VARDE_TEST_NUMERIC_SECRET_NUMBER" for item in found)


def test_dotenv_splits_only_on_newline(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("FIRST=abcdefgh\vSECOND=ijklmnop\nTHIRD=qrstuvwx", encoding="utf-8")
    found = values.from_dotenv(path)
    assert {item.name for item in found} == {"FIRST", "THIRD"}
    assert (
        next(item.value for item in found if item.name == "FIRST")
        == "abcdefgh\vSECOND=ijklmnop"
    )
