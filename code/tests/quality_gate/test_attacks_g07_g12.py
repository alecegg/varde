"""Gate attacks G7-G12 (validation plan section 10), one test per attack and language.

Every cell runs ``scan_repo`` end to end against a pinned snapshot under the
test-only ``gate-test-cal`` calibration (mechanism proof, not validation). The
attacks are the specification: an expectation is never edited to pass.

One attack cell cannot pass today because the scorer does not do what the
attack requires; it is a separate strict-xfail test whose assertion is the
unweakened expectation:

* G7 C#: see ``G7_CSHARP_DEFECT``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import gate_sources_cs
import gate_sources_py
import gate_sources_ts
import pytest
from conftest import file_scores, score_repo, write_files
from gate_snapshots import LANGUAGES, SNAPSHOTS, Snapshot
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.quality_pass.pass_ import read_measures
from varde_code.query import modes
from varde_code.scan import core

FLOOR = "quality-file-floor"
CAP = "quality-function-cap"
MEAN = "quality-scope-mean"
UNSCORED = "quality-unscored-share"
SUPPRESSED = "quality-suppressed"
TEMPLATE = Path(core.__file__).parent / "ci_templates" / "github-actions.yml"


@pytest.fixture
def gate_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    gate_calibration,
) -> Path:
    """An empty repo root on a neutral path, with scan using ``gate-test-cal``.

    A pytest ``test_*`` directory in the path would make every Python file a
    test path, so the root comes from ``mktemp`` instead of ``tmp_path``.
    """
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    monkeypatch.setattr(core, "load_calibration", lambda path: gate_calibration)
    return tmp_path_factory.mktemp("gate") / "repo"


def git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def commit_all(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base", "--no-verify")


def scan(root: Path, **options) -> dict:
    build(root, CodeExtractionProvider())
    return core.scan_repo({"repoRoot": str(root), "fullFindings": True, **options})


def findings(result: dict, rule_id: str) -> list[dict]:
    return [f for f in result["findings"] if f["rule_id"] == rule_id]


def flagged_files(result: dict, rule_id: str) -> set[str]:
    return {f["location"]["file"] for f in findings(result, rule_id)}


def bad_file_findings(result: dict) -> set[tuple[str, str, str]]:
    """Floor and cap findings as (rule, file, message): the untouched-file view."""
    return {
        (f["rule_id"], f["location"]["file"], f["message"])
        for f in result["findings"]
        if f["rule_id"] in (FLOOR, CAP)
    }


def mean_micro(scope) -> int:
    return scope.score.numerator // scope.score.denominator


def with_function(snapshot: Snapshot, source: str, blocks: int) -> str:
    """Append one debt-heavy function of ``blocks`` branch blocks to ``source``."""
    if snapshot.language == "python":
        return source + "\n\n" + gate_sources_py._debt(blocks)
    if snapshot.language == "typescript":
        return source + "\n" + gate_sources_ts._debt(blocks)
    method = gate_sources_cs._debt_method(blocks)
    return source.rstrip()[:-1].rstrip() + "\n\n" + method + "}\n"


def tiny_function_pile(snapshot: Snapshot, count: int, *, close: bool = True) -> str:
    """Many tiny clean functions in one file (closed class for C# unless asked)."""
    if snapshot.language == "csharp":
        method = (
            "    public static int Value{n}(int item)\n    {\n"
            "        return item + {n};\n    }\n\n"
        )
        body = "".join(method.replace("{n}", str(i)) for i in range(count))
        text = "namespace Gate;\n\npublic static class Pile\n{\n" + body
        return text + ("}\n" if close else "")
    return "".join(
        snapshot.filler_tiny.replace("{n}", str(i)) + "\n" for i in range(count)
    )


def caller_file(snapshot: Snapshot, statements: int = 10) -> str:
    """The edge caller: one function of straight-line code that calls the callee."""
    if snapshot.language == "python":
        body = "".join(f"    v{j} = v{j - 1} + {j}\n" for j in range(1, statements))
        return (
            "from gate.callee import compute\n\n\ndef run(value):\n"
            f"    v0 = compute(value)\n{body}    return v{statements - 1}\n"
        )
    if snapshot.language == "typescript":
        body = "".join(
            f"  const v{j} = v{j - 1} + {j};\n" for j in range(1, statements)
        )
        return (
            'import { compute } from "./callee";\n\n'
            "export function run(value: number): number {\n"
            f"  const v0 = compute(value);\n{body}  return v{statements - 1};\n}}\n"
        )
    body = "".join(
        f"        var v{j} = v{j - 1} + {j};\n" for j in range(1, statements)
    )
    return (
        "namespace Gate;\n\npublic static class Caller\n{\n"
        "    public static int Run(int value)\n    {\n"
        "        var v0 = Callee.Compute(value);\n"
        f"{body}        return v{statements - 1};\n"
        "    }\n}\n"
    )


TS_LINK = "export function f{i}(v: number): number {{\n  return f{j}(v) + 1;\n}}\n\n"
TS_LAST = "export function f{i}(v: number): number {{\n  return v;\n}}\n\n"
TS_ENTRY = "export function compute(value: number): number {\n  return f0(value);\n}\n"
CS_LINK = (
    "    public static int F{i}(int v)\n    {{\n        return F{j}(v) + 1;\n    }}\n\n"
)
CS_LAST = "    public static int F{i}(int v)\n    {{\n        return v;\n    }}\n\n"
CS_ENTRY = (
    "    public static int Compute(int value)\n    {\n"
    "        return F0(value);\n    }\n"
)


def deep_callee(snapshot: Snapshot, depth: int = 10) -> str:
    """The edge callee rewritten as a call chain ``depth`` deep."""
    indexes = range(depth)
    if snapshot.language == "python":
        links = "".join(
            f"def f{i}(v):\n    return f{i + 1}(v) + 1\n\n\n" for i in indexes
        )
        last = f"def f{depth}(v):\n    return v\n\n\n"
        return links + last + "def compute(value):\n    return f0(value)\n"
    if snapshot.language == "typescript":
        links = "".join(TS_LINK.format(i=i, j=i + 1) for i in indexes)
        return links + TS_LAST.format(i=depth) + TS_ENTRY
    links = "".join(CS_LINK.format(i=i, j=i + 1) for i in indexes)
    head = "namespace Gate;\n\npublic static class Callee\n{\n"
    return head + links + CS_LAST.format(i=depth) + CS_ENTRY + "}\n"


# G7: many tiny clean files (M-filepad).
G7_CSHARP_DEFECT = pytest.mark.xfail(
    strict=True,
    reason=(
        "scorer/calibration property, not the floor-exemption predicate: the "
        "tiny C# file (24 tokens, class wrapper) scores 58.1 > Y=38 because "
        "kappa_F (file_overhead) is 0 and its one small function costs little, "
        "so padding lifts the mean above max(before, Y); see "
        "notes/g7-predicate.md in the scan-gate plan"
    ),
)


@pytest.mark.parametrize(
    "language",
    [
        pytest.param(name, marks=G7_CSHARP_DEFECT) if name == "csharp" else name
        for name in LANGUAGES
    ],
)
def test_g7_tiny_file_padding_cannot_lift_the_mean_above_max_of_before_and_y(
    language, gate_root, gate_calibration, tmp_path_factory
):
    snapshot = SNAPSHOTS[language]
    y = gate_calibration.languages[language].parameters["Y"]
    padding = snapshot.filler_files(100, tiny=True)
    before = score_repo(
        tmp_path_factory.mktemp("before") / "repo", snapshot.files, gate_calibration
    )
    after = score_repo(gate_root, {**snapshot.files, **padding}, gate_calibration)

    assert mean_micro(after) <= max(mean_micro(before), y)
    padded = {f.path for f in after.files} & set(padding)
    assert padded == set(padding), "every padding file is scored, none dropped"
    assert after.tokens > before.tokens


# G8: large clean filler (M-dilute).
def clean_copies(snapshot: Snapshot, count: int) -> dict[str, str]:
    """Large clean filler: copies of the high-scoring clean file in new paths.

    The fixture generator ``filler_clean`` is 40 tiny functions per file, which
    the per-function overhead scores low, so it does not model clean filler.
    """
    clean = snapshot.files[snapshot.path("clean")]
    return {
        f"{snapshot.module_dir}/filler_{index:03d}.{snapshot.ext}": clean
        for index in range(count)
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_g8_dilution_raises_the_mean_and_keeps_findings_for_untouched_bad_files(
    language, gate_root, gate_calibration, tmp_path_factory
):
    snapshot = SNAPSHOTS[language]
    filler = clean_copies(snapshot, 12)
    before = score_repo(
        tmp_path_factory.mktemp("before") / "repo", snapshot.files, gate_calibration
    )
    write_files(gate_root, snapshot.files)
    listed_before = bad_file_findings(scan(gate_root))
    write_files(gate_root, filler)
    after_result = scan(gate_root)
    after = score_repo(
        tmp_path_factory.mktemp("after") / "repo",
        {**snapshot.files, **filler},
        gate_calibration,
    )

    assert mean_micro(after) > mean_micro(before), "dilution raises the mean"
    assert snapshot.path("debt") in {path for _, path, _ in listed_before}
    assert bad_file_findings(after_result) == listed_before
    assert after_result["gate"]["status"] == "fail"


# G9: changedSince hides an unchanged caller whose callee changed.
@pytest.mark.parametrize("language", LANGUAGES)
def test_g9_changed_since_limits_findings_but_the_mean_covers_the_scope(
    language, gate_root
):
    snapshot = SNAPSHOTS[language]
    caller, callee = snapshot.edge_caller, snapshot.edge_callee
    mid = snapshot.path("mid")
    write_files(gate_root, {**snapshot.files, caller: caller_file(snapshot)})
    commit_all(gate_root)
    write_files(
        gate_root,
        {
            callee: deep_callee(snapshot),
            mid: with_function(snapshot, snapshot.files[mid], 14),
        },
    )
    full = scan(gate_root)
    since = scan(gate_root, changedSince="HEAD")

    coverage = {m["path"]: m["call_coverage"] for m in read_measures(gate_root)}
    verdicts = [name for name, count in coverage[caller].items() if count]
    assert verdicts == ["resolved"], "recorded resolver verdict for the direct edge"
    assert caller in flagged_files(full, FLOOR), "the unchanged caller newly violates"
    assert snapshot.path("debt") in flagged_files(full, FLOOR)

    changed = {callee, mid}
    for rule_id in (FLOOR, CAP):
        assert flagged_files(since, rule_id) <= changed, rule_id
    assert mid in flagged_files(since, FLOOR)
    assert mid in flagged_files(since, CAP)
    assert caller not in flagged_files(since, FLOOR), "hidden in changedSince mode"
    assert findings(full, MEAN), "the snapshot mean is below X"
    assert [f["message"] for f in findings(since, MEAN)] == [
        f["message"] for f in findings(full, MEAN)
    ], "the mean covers the whole scope"
    assert "stay hidden in this mode" in TEMPLATE.read_text(encoding="utf-8")


# G10: a syntax-error file replaces a scored file, above 10% and above 20% unscored.
SYNTAX_ERROR_PILES = {"above-10-percent": 25, "above-20-percent": 60}
TSX_SYNTAX_ERROR = "export const Broken = () => <div>;\n"


def syntax_error_variants(snapshot: Snapshot, size: int) -> list[tuple[str, str]]:
    """(path, broken source) variants: a pile of valid code ending in a syntax error."""
    variants = [
        (
            snapshot.path("clean"),
            tiny_function_pile(snapshot, size, close=False) + snapshot.syntax_error,
        )
    ]
    if snapshot.language == "typescript":
        variants.append(
            (
                snapshot.path("tsx"),
                tiny_function_pile(snapshot, size) + TSX_SYNTAX_ERROR,
            )
        )
    return variants


@pytest.mark.parametrize("language", LANGUAGES)
def test_g10_syntax_error_share_raises_unscored_finding_then_blocks(
    language, gate_root, gate_calibration, tmp_path_factory
):
    snapshot = SNAPSHOTS[language]
    for label, size in SYNTAX_ERROR_PILES.items():
        for path, source in syntax_error_variants(snapshot, size):
            files = {**snapshot.files, path: source}
            root = tmp_path_factory.mktemp("g10") / "repo"
            write_files(root, files)
            result = scan(root)
            diagnostic_paths = {d.get("path") for d in result["diagnostics"]}

            unscored = findings(result, UNSCORED)
            assert path in diagnostic_paths, f"{label} {path}: not silently dropped"
            assert unscored, f"{label} {path}: quality-unscored-share finding"
            blocking = {f["evidence"]["blocking"] for f in unscored}
            assert blocking == ({1} if label == "above-20-percent" else {0}), label
            if label == "above-20-percent":
                gated = [
                    d
                    for d in result["diagnostics"]
                    if d.get("blocking") and d.get("rule_id") == UNSCORED
                ]
                assert gated, f"{label} {path}: blocking unscored-share diagnostic"


# G11: inline suppression on floor and cap violators.
def next_line_directive_before_function(snapshot: Snapshot, source: str) -> str:
    """Insert the next-line directive on the line above the debt function."""
    signature = {
        "python": "def x(",
        "typescript": "export function x(",
        "csharp": "public static int X(",
    }[snapshot.language]
    lines = source.splitlines(keepends=True)
    index = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith(signature)
    )
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines.insert(index, indent + snapshot.suppress_next_line)
    return "".join(lines)


@pytest.mark.parametrize("language", LANGUAGES)
def test_g11_inline_suppression_does_not_hide_quality_findings_and_is_counted(
    language, gate_root
):
    snapshot = SNAPSHOTS[language]
    debt = snapshot.path("debt")
    plain = snapshot.files[debt]

    write_files(gate_root, {debt: snapshot.with_file_suppression(plain)})
    by_file = scan(gate_root)
    write_files(gate_root, {debt: next_line_directive_before_function(snapshot, plain)})
    by_line = scan(gate_root)

    assert debt in flagged_files(by_file, FLOOR)
    assert debt in flagged_files(by_file, CAP)
    assert by_file["gate"]["status"] == "fail"
    assert [f["evidence"]["suppressed"] for f in findings(by_file, SUPPRESSED)] == [2]
    assert debt in flagged_files(by_line, FLOOR)
    assert debt in flagged_files(by_line, CAP)
    assert [f["evidence"]["suppressed"] for f in findings(by_line, SUPPRESSED)] == [1]


# G12: tests, tooling, vendored and unscoped code; a missing changedSince ref.
def moved_debt_paths(snapshot: Snapshot) -> dict[str, str]:
    name = snapshot.path("debt").rsplit("/", 1)[1]
    base = name.rsplit(".", 1)[0]
    ext = snapshot.ext
    named = {f"spec/{base}.{ext}": "tests", f"scripts/{base}.{ext}": "tooling"}
    named.update(dict.fromkeys(snapshot.test_paths, "tests"))
    named[f"vendor/{base}.{ext}"] = "repo"
    named[f"stray/off/module/{base}.{ext}"] = "repo"
    named[name] = "repo"
    return named


@pytest.mark.parametrize("language", LANGUAGES)
def test_g12_moved_code_keeps_findings_and_scopes_report_tokens_separately(
    language, gate_root, gate_calibration, tmp_path_factory
):
    snapshot = SNAPSHOTS[language]
    debt = snapshot.path("debt")
    others = {p: s for p, s in snapshot.files.items() if p != debt}
    for target, scope in moved_debt_paths(snapshot).items():
        root = tmp_path_factory.mktemp("g12") / "repo"
        write_files(root, {**others, target: snapshot.files[debt]})
        result = scan(root)

        assert target in flagged_files(result, FLOOR), target
        assert target in flagged_files(result, CAP), target
        assert not findings(result, UNSCORED), f"{target}: not production unscored"
        assert debt not in flagged_files(result, FLOOR) or target == debt
        means = {f["evidence"]["scope"]: f["evidence"] for f in findings(result, MEAN)}
        if scope != "repo":
            total = score_repo(
                tmp_path_factory.mktemp("g12") / "repo",
                {**others, target: snapshot.files[debt]},
                gate_calibration,
            )
            moved = file_scores(total)[target].tokens
            assert means[scope]["tokens"] == moved, target
            assert "repo" not in means, f"{target}: debt left the production mean"


@pytest.mark.parametrize("language", LANGUAGES)
def test_g12_missing_changed_since_ref_is_a_blocking_diagnostic(language, gate_root):
    snapshot = SNAPSHOTS[language]
    write_files(gate_root, snapshot.files)
    commit_all(gate_root)
    result = scan(gate_root, changedSince="no-such-ref")

    blocking = [d for d in result["diagnostics"] if d.get("blocking")]
    assert any("no-such-ref" in d["message"] for d in blocking)
    assert result["gate"]["blocking_diagnostic_count"] >= 1
    assert findings(result, FLOOR), "findings are not silently dropped"


@pytest.mark.parametrize("language", LANGUAGES)
def test_g12_code_outside_any_module_is_still_in_the_root_scope(language, gate_root):
    """v1 has no configurable module scopes: the root scope covers all code.

    The design's "unscoped tokens raise a diagnostic" has no v1 trigger because
    nothing can be unscoped, so this cell asserts the root scope still scores
    code outside every module directory instead of dropping it.
    """
    snapshot = SNAPSHOTS[language]
    debt = snapshot.path("debt")
    stray = f"loose.{snapshot.ext}"
    files = {p: s for p, s in snapshot.files.items() if p != debt}
    write_files(gate_root, {**files, stray: snapshot.files[debt]})
    result = scan(gate_root)

    assert stray in flagged_files(result, FLOOR)
    assert stray in flagged_files(result, CAP)
    repo_mean = [f for f in findings(result, MEAN) if f["evidence"]["scope"] == "repo"]
    assert repo_mean and repo_mean[0]["evidence"]["tokens"] > 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_g12_code_moved_under_build_is_not_dropped(language, gate_root):
    snapshot = SNAPSHOTS[language]
    debt = snapshot.path("debt")
    target = f"build/{debt.rsplit('/', 1)[1]}"
    files = {p: s for p, s in snapshot.files.items() if p != debt}
    write_files(gate_root, {**files, target: snapshot.files[debt]})
    result = scan(gate_root)

    assert target in flagged_files(result, FLOOR)
