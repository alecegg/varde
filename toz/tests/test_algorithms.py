from __future__ import annotations

from varde_core.redact import RedactConfig, Redacted, Redactor, SecretValue
from varde_toz.strategies import Strategy, chunk_default_content, detect


def redact(
    text: str, *, builtin: bool = True, patterns=(), values=None, reveal: int = 2
) -> Redacted:
    secrets = [SecretValue(name, value) for name, value in (values or {}).items()]
    config = RedactConfig(
        builtin=builtin, patterns=patterns, values=secrets, reveal=reveal
    )
    return Redactor(config).redact(text)


def test_redaction_replaces_github_and_aws_credentials_with_labels() -> None:
    token = "ghp_" + "a" * 36
    text = f"credential {token}; key AKIA1234567890ABCDEF"
    assert redact(text).text == "credential [redacted:github]; key [redacted:aws-key]"


def test_redaction_prefers_longer_overlapping_values() -> None:
    assert redact(
        "prefix abcdef suffix", builtin=False, values={"SHORT": "abc", "LONG": "abcdef"}
    ).text == ("prefix [redacted:value:LONG] suffix")


def test_redaction_handles_overlapping_value_matches() -> None:
    assert redact("aaa", builtin=False, values={"PAIR": "aa"}).text == (
        "[redacted:value:PAIR]a"
    )


def test_chunking_keeps_handwritten_lines_intact() -> None:
    text = "\n".join(
        line
        for number in range(15)
        for line in (f"# Section {number:02}", f"content for section {number:02}")
    )
    chunks = chunk_default_content(text)
    assert len(chunks) > 1
    assert "\n".join(chunk.body for chunk in chunks) == text
    for chunk in chunks:
        expected_lines = text.splitlines()[chunk.line_start - 1 : chunk.line_end]
        assert chunk.body.splitlines() == expected_lines


def test_chunking_selects_markdown_and_fixed_strategies_by_content() -> None:
    markdown = "# First\nintro\n## Second\ndetails\n"
    plain = "".join(f"ordinary line {number}\n" for number in range(30))
    markdown_chunks = chunk_default_content(markdown)
    plain_chunks = chunk_default_content(plain)
    assert detect(markdown) is Strategy.MARKDOWN
    assert len(markdown_chunks) == 1
    assert "First" in markdown_chunks[0].title
    assert "Second" in markdown_chunks[0].title
    assert detect(plain) is Strategy.FIXED
    assert "ordinary line 0" in plain_chunks[0].body


def test_fixed_chunking_keeps_small_generated_input_in_order() -> None:
    text = "ordinary generated prose line\n" * 30
    assert detect(text) == Strategy.FIXED
    chunks = chunk_default_content(text)
    assert "".join(chunk.body + "\n" for chunk in chunks) == text
