"""A17: code token counts measured against an independent lexical reference.

The reference is a separate lexical scanner (``accuracy_reference_tokens.py``)
that shares no code with the facts engine. Per-fixture references, the
derivation method, the hand-checked fixtures and the TSX JSX rules are recorded
in ``fixtures/accuracy/README.md``.
"""

from __future__ import annotations

import io
import tokenize

import pytest
from accuracy_audit import (
    RELEASE_LANGUAGE,
    fixture_facts,
    fixture_language,
    fixture_path,
    labels,
    record_rate,
)
from accuracy_reference_tokens import reference_token_count, reference_tokens

pytestmark = pytest.mark.slow

TOKEN_LABELS = labels("tokens.json")
TOKEN_PATHS = sorted(TOKEN_LABELS)
TOLERANCE = 0.02

RECORDED_FILE_TOTALS = {}
RECORDED_LANGUAGE_TOTALS = {
    "python": (736, 736),
    "typescript/javascript/tsx": (1139, 1144),
    "java": (693, 691),
    "go": (534, 534),
    "rust": (680, 682),
    "csharp": (622, 621),
    "cpp": (643, 642),
}

# Hand-derived reference counts for TSX snippets exercising the documented JSX
# rules: `</` is one token and a text run is one token.
JSX_SNIPPETS = (
    ("const a = <br />;\n", 8),
    ("const b = <></>;\n", 8),
    ("const d = <p>text</p>;\n", 11),
    ("const c = <p>{value} and more</p>;\n", 14),
)


def _delta(engine: int, reference: int) -> float:
    return (engine - reference) / reference


def _language_totals(release: str) -> tuple[int, int]:
    engine = reference = 0
    for relative_path in TOKEN_PATHS:
        metadata = TOKEN_LABELS[relative_path]
        if RELEASE_LANGUAGE[metadata["language"]] != release:
            continue
        engine += fixture_facts(relative_path)["tokens"]
        reference += metadata["reference"]
    return engine, reference


def _all_language_lines():
    for release in sorted(set(RELEASE_LANGUAGE.values())):
        engine, reference = _language_totals(release)
        yield (
            release,
            (
                f"engine={engine} reference={reference} "
                f"delta={_delta(engine, reference):+.2%}"
            ),
        )


def _out_of_tolerance_files() -> dict[str, tuple[int, int]]:
    return {
        relative_path: (
            fixture_facts(relative_path)["tokens"],
            TOKEN_LABELS[relative_path]["reference"],
        )
        for relative_path in TOKEN_PATHS
        if abs(
            _delta(
                fixture_facts(relative_path)["tokens"],
                TOKEN_LABELS[relative_path]["reference"],
            )
        )
        > TOLERANCE
    }


@pytest.mark.parametrize("relative_path", TOKEN_PATHS)
def test_a17_token_labels_match_the_independent_lexical_scanner(relative_path):
    path = fixture_path(relative_path)
    source = path.read_text()
    script = reference_token_count(source, fixture_language(path))

    assert script == TOKEN_LABELS[relative_path]["reference"]


@pytest.mark.parametrize("relative_path", TOKEN_PATHS)
def test_a17_token_count_per_fixture_is_within_two_percent(relative_path):
    reference = TOKEN_LABELS[relative_path]["reference"]
    engine = fixture_facts(relative_path)["tokens"]
    delta = _delta(engine, reference)

    print(
        f"A17 {relative_path}: engine={engine} reference={reference} delta={delta:+.2%}"
    )
    assert abs(delta) <= TOLERANCE


@pytest.mark.parametrize("release", sorted(set(RELEASE_LANGUAGE.values())))
def test_a17_token_totals_are_within_two_percent_per_release_language(release):
    engine, reference = _language_totals(release)
    lines = [f"{name}: {value}" for name, value in _all_language_lines()]
    record_rate("A17 per release language", *lines)
    print("A17 " + "\nA17 ".join(lines))

    assert abs(_delta(engine, reference)) <= TOLERANCE


def test_a17_out_of_tolerance_files_are_the_recorded_set():
    computed = _out_of_tolerance_files()
    print(
        "A17 out of tolerance: "
        + ", ".join(
            f"{path} engine={engine} reference={reference} "
            f"delta={_delta(engine, reference):+.2%}"
            for path, (engine, reference) in sorted(computed.items())
        )
    )

    assert computed == RECORDED_FILE_TOTALS


def test_a17_language_totals_are_the_recorded_set():
    computed = {
        release: _language_totals(release)
        for release in sorted(set(RELEASE_LANGUAGE.values()))
    }

    assert computed == RECORDED_LANGUAGE_TOTALS


def test_a17_python_reference_matches_the_stdlib_tokenizer():
    """Cross-check the lexical scanner for Python against ``tokenize``.

    All four fixtures agree once PEP 701 f-string parts are collapsed into one
    literal, which is the reference rule for interpolated strings.
    """
    for relative_path in sorted(
        path for path in TOKEN_PATHS if TOKEN_LABELS[path]["language"] == "python"
    ):
        source = fixture_path(relative_path).read_text()

        assert _stdlib_token_count(source) == len(reference_tokens(source, "python")), (
            relative_path
        )


def test_a17_hand_counted_fixtures_match_the_documented_breakdown():
    """Pin the two per-line hand tallies recorded in the fixture README.

    The lexical token counts and the string-weight corrections were counted by
    hand; a scanner change that moves either must update the README.
    """
    basics = reference_tokens(fixture_path("tokens/cpp/basics.cpp").read_text(), "cpp")
    numeric = reference_tokens(
        fixture_path("tokens/python/numeric.py").read_text(), "python"
    )

    assert (len(basics), sum(token.weight for token in basics)) == (87, 88)
    assert (len(numeric), sum(token.weight for token in numeric)) == (176, 183)


@pytest.mark.parametrize(("snippet", "expected"), JSX_SNIPPETS)
def test_a17_tsx_jsx_rules_count_closing_tags_and_text_runs(snippet, expected):
    assert reference_token_count(snippet, "tsx") == expected


def _stdlib_token_count(source: str) -> int:
    """Count Python tokens with the stdlib tokenizer, one token per f-string."""
    skipped = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    count = fstring_depth = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in skipped:
            continue
        if token.type == tokenize.FSTRING_START:
            fstring_depth += 1
            count += fstring_depth == 1
            continue
        if token.type == tokenize.FSTRING_END:
            fstring_depth -= 1
            continue
        if fstring_depth:
            continue
        count += 1
    return count
