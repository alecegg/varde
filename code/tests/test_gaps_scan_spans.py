from pathlib import Path

from varde_code.model import Span
from varde_code.rules.clone_verification import verify
from varde_code.rules.finding import Finding, Location
from varde_code.rules.model import Rule, RuleKind, Severity, Verification


def test_clone_verification_matches_utf8_byte_spans_after_non_ascii_text(
    tmp_path: Path,
) -> None:
    source = "# café\ndef same():\n    return 1 + 2\n"
    start_byte = len("# café\n".encode())
    end_byte = len(source.encode("utf-8")) - 1
    candidates = []
    for name in ("a.py", "b.py", "c.py"):
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        span = Span(start_byte, end_byte, 2, 0, 3, 16)
        candidates.append(
            Finding(
                f"candidate-{name}",
                "clone",
                Severity.WARNING,
                "clone",
                Location(str(path), span),
                {},
                None,
            )
        )
    clone_rule = Rule(
        id="clone",
        kind=RuleKind.SQL,
        severity=Severity.WARNING,
        message="clone",
        verification=Verification.EXACT_CLONE,
        thresholds={"min_tokens": 1, "min_members": 3, "min_span_lines": 0},
    )

    findings, diagnostics = verify(clone_rule, tmp_path, candidates)

    assert diagnostics == []
    assert len(findings) == 3


def test_clone_verification_reports_span_ending_inside_utf8_character(
    tmp_path: Path,
) -> None:
    source = 'def same():\n    return "café"\n'
    paths = [tmp_path / name for name in ("a.py", "b.py", "c.py")]
    for path in paths:
        path.write_text(source, encoding="utf-8")
    start_byte = 0
    end_byte = len(b'def same():\n    return "caf') + 1
    candidates = [
        Finding(
            f"candidate-{path.name}",
            "clone",
            Severity.WARNING,
            "clone",
            Location(str(path), Span(start_byte, end_byte, 1, 0, 2, 16)),
            {},
            None,
        )
        for path in paths
    ]
    clone_rule = Rule(
        id="clone",
        kind=RuleKind.SQL,
        severity=Severity.WARNING,
        message="clone",
        verification=Verification.EXACT_CLONE,
        thresholds={"min_tokens": 1, "min_members": 3, "min_span_lines": 0},
    )

    findings, diagnostics = verify(clone_rule, tmp_path, candidates)

    assert findings == []
    assert len(diagnostics) == 3
    assert all("character boundary" in item.reason for item in diagnostics)


def test_clone_verification_reports_span_extending_beyond_source(
    tmp_path: Path,
) -> None:
    source = "def same():\n    return 1 + 2\n"
    paths = [tmp_path / name for name in ("a.py", "b.py", "c.py")]
    for path in paths:
        path.write_text(source, encoding="utf-8")
    candidates = [
        Finding(
            f"candidate-{path.name}",
            "clone",
            Severity.WARNING,
            "clone",
            Location(
                str(path),
                Span(0, len(source.encode("utf-8")) + 1, 1, 0, 2, 16),
            ),
            {},
            None,
        )
        for path in paths
    ]
    clone_rule = Rule(
        id="clone",
        kind=RuleKind.SQL,
        severity=Severity.WARNING,
        message="clone",
        verification=Verification.EXACT_CLONE,
        thresholds={"min_tokens": 1, "min_members": 3, "min_span_lines": 0},
    )

    findings, diagnostics = verify(clone_rule, tmp_path, candidates)

    assert findings == []
    assert len(diagnostics) == 3
    assert all("span extends beyond source" in item.reason for item in diagnostics)
