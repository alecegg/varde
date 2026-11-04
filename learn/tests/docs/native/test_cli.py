"""Native command behavior checks using small authored inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from varde_learn.docs.cli import run


def run_doc(args: list[str], capsys) -> tuple[int, str, str]:
    status = run(args)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_lint_reports_sentence_units_and_accepts_short_prose(
    tmp_path: Path, capsys
) -> None:
    valid = tmp_path / "valid-skill"
    valid.mkdir()
    (valid / "SKILL.md").write_text(
        (  # noqa: UP034 - Explicit grouping is required for split fixture text.
            "---\nname: valid-skill\ndescription: A concise test skill.\n---\n"
            "# Valid\nRead the input.\n"
        )
    )
    status, output, _ = run_doc(["lint", "--json", str(valid)], capsys)
    assert status == 0
    assert json.loads(output)["data"]["findings"] == []

    long_skill = tmp_path / "long"
    long_skill.mkdir()
    paragraph = " ".join(f"Sentence {number}." for number in range(1, 8))
    (long_skill / "SKILL.md").write_text(
        f"---\nname: long\ndescription: d\n---\n# Long\n{paragraph}\n"
    )
    status, output, _ = run_doc(["lint", "--json", str(long_skill)], capsys)
    assert status == 1
    findings = json.loads(output)["data"]["error"]["details"]["findings"]
    assert any(
        finding["line"] == 6 and finding["message"] == "(unit, 7 sentences)"
        for finding in findings
    )

    short_skill = tmp_path / "short"
    short_skill.mkdir()
    (short_skill / "SKILL.md").write_text(
        "---\nname: short\ndescription: d\n---\n# Short\nOne. Two. Three.\n"
    )
    status, output, _ = run_doc(["lint", "--json", str(short_skill)], capsys)
    assert status == 0
    assert json.loads(output)["data"]["findings"] == []


def test_frontmatter_reports_valid_missing_and_uppercase_names(
    tmp_path: Path, capsys
) -> None:
    valid = tmp_path / "valid-skill"
    valid.mkdir()
    (valid / "SKILL.md").write_text(
        '---\nname: valid-skill\ndescription: "Test skill."\n---\n'
    )
    status, output, _ = run_doc(["frontmatter", "--json", str(valid)], capsys)
    assert status == 0
    assert json.loads(output)["data"]["results"][0]["ok"]

    missing = tmp_path / "missing"
    missing.mkdir()
    (missing / "SKILL.md").write_text('---\ndescription: "Test skill."\n---\n')
    status, output, _ = run_doc(["frontmatter", "--json", str(missing)], capsys)
    assert status == 1
    details = json.loads(output)["data"]["error"]["details"]
    assert any("name" in error for error in details["results"][0]["errors"])

    uppercase = tmp_path / "uppercase"
    uppercase.mkdir()
    (uppercase / "SKILL.md").write_text(
        '---\nname: UpperCase\ndescription: "Test skill."\n---\n'
    )
    status, output, _ = run_doc(["frontmatter", "--json", str(uppercase)], capsys)
    assert status == 1
    details = json.loads(output)["data"]["error"]["details"]
    assert details["results"][0]["errors"]


def test_flow_reports_routes_orphans_mermaid_and_stale_documents(
    tmp_path: Path, capsys
) -> None:
    skill = tmp_path / "sample"
    refs = skill / "references"
    refs.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "# Sample\n\n| Request | Read |\n|---|---|\n| Start | `references/a.md` |\n"
    )
    (refs / "a.md").write_text("Read `references/b.md` next.\n")
    (refs / "b.md").write_text("Finish here.\n")
    (refs / "orphan.md").write_text("Unlinked content.\n")

    status, output, _ = run_doc(["flow", "--json", str(skill)], capsys)
    assert status == 0
    result = json.loads(output)["data"][0]
    assert [route["route"] for route in result["routes"]] == ["Start"]
    assert result["routes"][0]["files"] == ["references/a.md", "references/b.md"]
    assert result["findings"]["unreferenced"] == ["references/orphan.md"]

    status, output, _ = run_doc(["flow", "--mermaid", str(skill)], capsys)
    assert status == 0
    assert "SKILL.md" in output
    assert "references/a.md" in output
    assert "references/b.md" in output

    (skill / "FLOW.md").write_text("stale\n")
    status, _, _ = run_doc(["flow", "--check", str(skill)], capsys)
    assert status == 1
    status, _, _ = run_doc(["flow", "--write", str(skill)], capsys)
    assert status == 0
    status, _, _ = run_doc(["flow", "--check", str(skill)], capsys)
    assert status == 0


def test_spec_inventory_lists_authored_source_and_reports_missing_repository(
    tmp_path: Path, capsys
) -> None:
    repository = tmp_path / "repo"
    knowledge = tmp_path / "knowledge"
    working = tmp_path / "working"
    source = repository / "src" / "sample" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")
    (knowledge / "specs").mkdir(parents=True)
    working.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "initial"], check=True
    )

    def blob_hash(data: bytes) -> str:
        header = f"blob {len(data)}\0".encode()
        return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Fixture reproduces Git object IDs.

    digest = blob_hash(source.read_bytes())
    aggregate = blob_hash(f"src/sample/main.py{digest}".encode())
    (knowledge / "specs" / "sample.md").write_text(
        (  # noqa: UP034 - Explicit grouping is required for split fixture text.
            "---\ntype: spec\ndomain: sample\nsource_roots:\n  - src/sample\n"
            "covered_paths:\n  - src/sample/main.py\n"
            f"source_hash: {aggregate}\nsources:\n  - path: src/sample/main.py\n"
            f"    hash: {digest}\n"
            "---\nSample source.\n"
        )
    )
    args = [
        "spec",
        "inventory",
        "--repository",
        str(repository),
        "--knowledge",
        str(knowledge),
        "--working",
        str(working),
        "--json",
    ]
    status, output, _ = run_doc(args, capsys)
    assert status == 0
    domains = {item["domain"] for item in json.loads(output)["data"]["domains"]}
    assert "sample" in domains

    args[args.index(str(repository))] = str(tmp_path / "missing-repository")
    status, _, error = run_doc(args, capsys)
    assert status == 1
    assert "repository does not exist" in error
