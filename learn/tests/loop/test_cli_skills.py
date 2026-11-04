from __future__ import annotations

import io

import pytest
from varde_learn.loop import cli_skills

VERBS = (
    "demand",
    "candidates",
    "extract",
    "reset",
    "accept",
    "reject",
    "report",
    "updates",
)
LOOP_VERBS = VERBS[1:]


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def call(*argv: str) -> tuple[int, str, str]:
    out = Io()
    code = cli_skills.run(list(argv), out)
    return code, out.stdout.getvalue(), out.stderr.getvalue()


def test_group_help_lists_all_verbs() -> None:
    code, out, _ = call("--help")
    assert code == 0
    for verb in VERBS:
        assert f"  {verb}" in out


@pytest.mark.parametrize("verb", LOOP_VERBS)
def test_verb_help_prints_its_file(verb: str) -> None:
    code, out, _ = call(verb, "--help")
    assert code == 0
    assert f"varde learn skills {verb}" in out


def test_unknown_verb_exits_2() -> None:
    code, _, err = call("gate")
    assert code == 2
    assert "unknown skills command" in err


def test_missing_verb_module_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(cli_skills.VERB_MODULES, "report", "cli_skills_nonexistent")
    code, _, err = call("report")
    assert code == 2
    assert "not yet available" in err


def test_verb_dispatches_to_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        @staticmethod
        def run(rest: list[str], io: object | None) -> int:
            return 7 if rest == ["x"] else 1

    monkeypatch.setattr(cli_skills, "_load", lambda name: Fake)
    assert call("extract", "x")[0] == 7


def _extract(tmp_path, *argv: str) -> tuple[int, str, str]:
    from varde_learn.loop import cli_skills_extract

    out = Io()
    code = cli_skills_extract.run(list(argv), out, roots=[tmp_path])
    return code, out.stdout.getvalue(), out.stderr.getvalue()


@pytest.fixture
def package(tmp_path):
    how = tmp_path / "how" / "varde-x"
    how.mkdir(parents=True)
    for step in ("repo-map", "alpha"):
        (how / f"{step}.md").write_text(f"---\ntopic: varde-x/{step}\n---\n\nBody.\n")
    agent = tmp_path / "agents" / "varde-a"
    agent.mkdir(parents=True)
    profile = {
        "name": "varde-a",
        "instructions": "Intro\n\n## Do Work\n\nx\n\n## Report\n\ny\n",
    }
    (tmp_path / "agents" / "capabilities.json").write_text(
        __import__("json").dumps({"profiles": [profile]})
    )
    return tmp_path


def test_extract_without_step_lists_skill_steps(package) -> None:
    code, out, _ = _extract(package, "varde-x")
    assert (code, out) == (0, "alpha\nrepo-map\n")


def test_extract_without_step_lists_agent_sections_as_json(package) -> None:
    import json

    code, out, _ = _extract(package, "varde-a", "--json")
    assert code == 0
    assert json.loads(out)["data"] == {"steps": ["do-work", "report"]}


def test_extract_unknown_step_lists_valid_steps(package) -> None:
    code, _, err = _extract(package, "varde-x", "nope")
    assert code == 2
    assert "valid steps: alpha, repo-map" in err


def test_extract_without_steps_or_skill_exits_2(package) -> None:
    code, _, err = _extract(package, "missing")
    assert code == 2
    assert "no steps for 'missing'" in err
