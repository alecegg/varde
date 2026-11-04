import json
from typing import Any, cast

import pytest
from varde_learn.docs.lint import InputError, json_envelope, lint, run


def test_file_lint_reports_audit_findings_and_text(tmp_path):
    (tmp_path / "demo").mkdir()
    path = tmp_path / "demo" / "SKILL.md"
    path.write_text(
        "---\nname: demo\ndescription: d\n---\n# Title\n\n" + "Sentence. " * 6,
        encoding="utf-8",
    )

    report = lint([path])

    assert report.files == 1
    assert report.errors() == 1
    assert "ERROR " in report.render_text()
    assert report.render_text().endswith("1 error(s), 0 warning(s) across 1 file(s).\n")


def test_directory_expands_skill_and_sorted_references(tmp_path):
    tmp_path = tmp_path / "demo"
    tmp_path.mkdir()
    (tmp_path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\n# Skill\n", encoding="utf-8"
    )
    references = tmp_path / "references"
    references.mkdir()
    (references / "z.md").write_text("# Z\n", encoding="utf-8")
    (references / "a.md").write_text("# A\n", encoding="utf-8")

    report = lint([tmp_path])

    assert report.files == 3
    assert [finding.path for finding in report.findings] == []


def test_empty_skill_directory_is_input_error(tmp_path):
    with pytest.raises(InputError, match="no Markdown files found"):
        lint([tmp_path])


def test_missing_path_is_input_error(tmp_path):
    with pytest.raises(InputError, match="no such file or directory"):
        lint([tmp_path / "missing.md"])


def test_json_envelope_success_and_negative_result(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text("# Title\n", encoding="utf-8")
    clean_report = lint([clean])
    assert json_envelope(clean_report)["outcome"] == "success"

    noisy = tmp_path / "noisy.md"
    noisy.write_text("# Title\n\n" + "Sentence. " * 6, encoding="utf-8")
    envelope = json_envelope(lint([noisy]))
    assert envelope["outcome"] == "negative-result"
    finding = cast("Any", envelope)["data"]["error"]["details"]["findings"][0]
    assert isinstance(finding, dict)
    assert finding["severity"] == "error"


def test_run_json_input_error_and_exit_codes(tmp_path):
    from io import StringIO

    stdout, stderr = StringIO(), StringIO()
    assert (
        run([tmp_path / "missing"], json_output=True, stdout=stdout, stderr=stderr) == 2
    )
    assert json.loads(stderr.getvalue())["data"]["error"]["code"] == "doc_lint_input"

    path = tmp_path / "clean.md"
    path.write_text("# Title\n", encoding="utf-8")
    assert run([path], stdout=stdout, stderr=stderr) == 0


def _how_file(tmp_path, step="first", *, meta=None, body="Do the thing.\n"):
    fields = {"topic": f"demo/{step}", "version": 1, "summary": "Do it", **(meta or {})}
    head = "".join(f"{k}: {v}\n" for k, v in fields.items() if v is not None)
    directory = tmp_path / "how" / "demo"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{step}.md"
    path.write_text(f"---\n{head}---\n\n{body}", encoding="utf-8")
    return path


def _rules(path):
    return [finding.rule.value for finding in lint([path]).findings]


def test_clean_how_file_passes(tmp_path):
    assert _rules(_how_file(tmp_path)) == []


def test_how_file_gets_sentence_warning(tmp_path):
    long_sentence = " ".join(["word"] * 30) + ".\n"
    assert "sentence" in _rules(_how_file(tmp_path, body=long_sentence))
    assert "sentence" not in _rules(_how_file(tmp_path, "short"))


def test_how_directory_and_skill_how_dir_expand(tmp_path):
    _how_file(tmp_path, "first")
    _how_file(tmp_path, "second")
    assert lint([tmp_path / "how"]).files == 2
    assert lint([tmp_path / "how" / "demo"]).files == 2


def test_how_body_over_token_cap_fails(tmp_path):
    ok = _how_file(tmp_path, "ok", body="x" * (300 * 4) + "\n")
    assert "how-tokens" not in _rules(ok)
    big = _how_file(tmp_path, "big", body="word " * 400 + "\n")
    assert "how-tokens" in _rules(big)


def test_how_summary_over_100_chars_fails(tmp_path):
    assert "how-summary" in _rules(_how_file(tmp_path, meta={"summary": "s" * 101}))


@pytest.mark.parametrize(
    "meta",
    [
        {"topic": "demo/other"},
        {"version": "x"},
        {"version": 0},
        {"summary": None},
        {"extra": "1"},
    ],
)
def test_how_schema_violations_fail(tmp_path, meta):
    assert "how-schema" in _rules(_how_file(tmp_path, meta=meta))


def test_how_without_frontmatter_fails(tmp_path):
    path = tmp_path / "how" / "demo" / "bare.md"
    path.parent.mkdir(parents=True)
    path.write_text("Just text.\n", encoding="utf-8")
    assert _rules(path) == ["how-schema"]


def test_lint_warns_when_a_skill_names_a_sibling_skill(tmp_path):
    for name in ("varde-one", "varde-two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    skill = tmp_path / "varde-one" / "SKILL.md"
    skill.write_text(
        "---\nname: varde-one\ndescription: d\n---\n# One\n\n"
        "See varde-two, not varde-one.\n",
        encoding="utf-8",
    )

    report = lint([tmp_path / "varde-one"])

    assert [f.rule.value for f in report.findings] == ["skill-refs"]
    assert report.errors() == 0


def test_lint_reads_eval_assertions_but_not_trigger_or_mutation_sets(tmp_path):
    skill = tmp_path / "varde-one"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: varde-one\ndescription: d\n---\n# One\n", encoding="utf-8"
    )
    cases = {"evals": [{"id": 1, "assertions": ["Cites references/a.md", "Runs x"]}]}
    for name in ("evals.json", "trigger-queries.json", "mutations.json"):
        (skill / "evals" / name).write_text(json.dumps(cases), encoding="utf-8")

    report = lint([skill])

    assert [(f.rule.value, f.path.rsplit("/", 1)[1]) for f in report.findings] == [
        ("eval-content", "evals.json")
    ]
    assert report.errors() == 0


def test_lint_reads_eval_assertions_from_skill_md_path(tmp_path):
    skill = tmp_path / "varde-one"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: varde-one\ndescription: d\n---\n# One\n", encoding="utf-8"
    )
    cases = {"evals": [{"id": 1, "assertions": ["Cites references/a.md"]}]}
    (skill / "evals" / "evals.json").write_text(json.dumps(cases), encoding="utf-8")

    report = lint([skill / "SKILL.md"])
    assert [f.rule.value for f in report.findings] == ["eval-content"]


def test_cli_lint_of_skill_md_path_prints_eval_content_warning(tmp_path, capsys):
    from varde_learn.docs.cli import run

    skill = tmp_path / "varde-one"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: varde-one\ndescription: d\n---\n# One\n", encoding="utf-8"
    )
    cases = {"evals": [{"id": 1, "assertions": ["Cites references/a.md"]}]}
    (skill / "evals" / "evals.json").write_text(json.dumps(cases), encoding="utf-8")

    assert run(["lint", str(skill / "SKILL.md")]) == 0
    out = capsys.readouterr().out
    assert "evals.json:" in out and "asserts skill content" in out
