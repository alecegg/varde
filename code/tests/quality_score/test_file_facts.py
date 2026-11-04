import subprocess
from pathlib import Path

import pytest
from varde_code.quality_score import file_facts

SIMPLE = "def add(a, b):\n    return a + b\n"
BRANCHY = (
    "def decide(a, b, c):\n"
    "    if a:\n"
    "        for x in b:\n"
    "            if x and c:\n"
    "                while x > 0:\n"
    "                    x -= 1\n"
    "    return c\n"
)


def git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "mod.py").write_text(SIMPLE, encoding="utf-8")
    git(tmp_path, "add", "mod.py")
    git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


def test_facts_at_head_equal_facts_at_explicit_head(repo: Path) -> None:
    assert file_facts.facts_for_file(repo, "mod.py") == file_facts.facts_for_file(
        repo, "mod.py", ref="HEAD"
    )


def test_facts_at_older_ref_differ_after_a_committed_edit(repo: Path) -> None:
    first = file_facts.head_commit(repo)
    (repo / "mod.py").write_text(BRANCHY, encoding="utf-8")
    git(repo, "commit", "-q", "-am", "two")
    now = file_facts.facts_for_file(repo, "mod.py")
    before = file_facts.facts_for_file(repo, "mod.py", ref=first)
    assert now != before
    assert before["functions"][0]["name"] == "add"
    assert now["functions"][0]["name"] == "decide"


def test_missing_path_or_language_raises(repo: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_facts.facts_for_file(repo, "nope.py")
    with pytest.raises(ValueError, match="no supported language"):
        file_facts.language_of("README.md")


def test_list_files_is_sorted_and_filtered_by_language(repo: Path) -> None:
    (repo / "b.py").write_text(SIMPLE, encoding="utf-8")
    (repo / "a.py").write_text(SIMPLE, encoding="utf-8")
    (repo / "x.ts").write_text("export const x = 1;\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "more")
    assert file_facts.list_files(repo, "python") == ["a.py", "b.py", "mod.py"]
    assert file_facts.list_files(repo, "typescript") == ["x.ts"]


def test_exact_facts_adds_nesting_vague_names_and_delegation_for_python() -> None:
    source = (
        "def wrap(x):\n    return inner(x)\n\n"
        "def work(items):\n"
        "    tmp = []\n"
        "    for item in items:\n"
        "        if item:\n"
        "            tmp.append(item)\n"
        "    return tmp\n"
    )
    record = file_facts.exact_facts(source, "python", "m.py")
    by_name = {fn["name"]: fn for fn in record["functions"]}
    assert by_name["wrap"]["delegates"] is True
    assert by_name["work"]["delegates"] is False
    assert by_name["work"]["vague_names"] == 2
    assert by_name["work"]["max_nesting"] == 1
    assert by_name["wrap"]["max_nesting"] == 0
    typescript = file_facts.exact_facts(
        "function f() { return g(); }\n", "typescript", "m.ts"
    )
    assert "delegates" not in typescript["functions"][0]


def test_option_like_ref_is_refused_and_creates_no_file(
    repo: Path, tmp_path: Path
) -> None:
    target = tmp_path / "pwned"
    for ref in (f"--output={target}", "-x"):
        with pytest.raises(ValueError, match="invalid git ref"):
            file_facts.read_at(repo, "mod.py", ref)
        with pytest.raises(ValueError, match="invalid git ref"):
            file_facts.list_files(repo, "python", ref)
    assert not list(tmp_path.glob("pwned*"))


def test_unknown_ref_is_a_value_error_not_a_missing_file(repo: Path) -> None:
    with pytest.raises(ValueError, match="unknown git ref"):
        file_facts.read_at(repo, "mod.py", "nonexistent")


def test_csharp_bodyless_members_are_not_functions() -> None:
    source = b"""namespace N {
public interface IV { object GetValue(object target); }
public abstract class A {
  public abstract int Foo(int x);
  public int Ok(int x) { return x + 1; }
  public int Expr(int x) => x + 1;
}
}"""
    record = file_facts.exact_facts(source, "csharp", "a.cs")
    ids = [f["id"] for f in record["functions"]]
    assert ids == ["a.cs::A.Ok#1", "a.cs::A.Expr#1"]
