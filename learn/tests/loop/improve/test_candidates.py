from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from varde_learn.loop import cli_skills_candidates
from varde_learn.loop.improve import candidates

FIXTURE = Path(__file__).parents[1] / "fixtures" / "improve"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def demand() -> dict:
    return {
        "steps": [
            {"step": "s-add/a", "requests": 2, "failures": 1},
            {"step": "s-add/tool", "requests": 5, "failures": 0},
        ],
        "skills": [
            {"skill": "s-add", "friction_items": 1, "how_skip_friction": 1},
            {"skill": "s-add-big", "friction_items": 3, "how_skip_friction": 0},
        ],
    }


def groups() -> dict:
    targets = candidates.gather_targets([FIXTURE])
    return candidates.rank(targets, demand(), frozenset({"s-add/tool"}))


def test_agent_tokens_adds_loaded_skills_and_ignores_missing_ones() -> None:
    sizes = {"a": 100, "b": 50}
    base = candidates.agent_tokens("", sizes, [])
    assert candidates.agent_tokens("", sizes, ["a", "b", "gone"]) == base + 150


def test_agent_with_large_skills_trims_and_small_agent_stays_unlisted(
    tmp_path: Path,
) -> None:
    for name in ("big", "small"):
        (tmp_path / "skills" / name).mkdir(parents=True)
        (tmp_path / "skills" / name / "SKILL.md").write_text(
            "word " * (1500 if name == "big" else 5)
        )
    (tmp_path / "agents" / "heavy").mkdir(parents=True)
    (tmp_path / "agents" / "light").mkdir()
    profiles = [
        {"name": "heavy", "instructions": "go", "skills": ["big"]},
        {"name": "light", "instructions": "go", "skills": ["small"]},
    ]
    (tmp_path / "agents" / "capabilities.json").write_text(
        json.dumps({"profiles": profiles})
    )
    found = candidates.rank(candidates.gather_targets([tmp_path]), {})
    assert "heavy" in names(found["trim"]) + names(found["reset"])
    assert "light" not in {c.name for g in found.values() for c in g}


def names(group: list) -> list[str]:
    return [c.name for c in group]


def test_one_direction_per_target_and_order_within_groups() -> None:
    found = groups()
    assert names(found["add"]) == ["s-add-big", "s-add"]
    assert names(found["reset"]) == ["s-reset"]
    assert sorted(names(found["trim"])) == ["agent-trim", "s-trim"]
    everyone = [n for group in found.values() for n in names(group)]
    assert len(everyone) == len(set(everyone))


def test_quiet_targets_are_not_listed_and_agents_are_targets() -> None:
    found = groups()
    everyone = [c for group in found.values() for c in group]
    assert "s-quiet" not in {c.name for c in everyone}
    assert "agent-quiet" not in {c.name for c in everyone}
    agent = next(c for c in everyone if c.name == "agent-trim")
    assert agent.kind == "agent"


def test_evidence_columns() -> None:
    add = next(c for c in groups()["add"] if c.name == "s-add")
    assert (add.friction, add.how_skip, add.failures) == (2, 1, 1)
    assert (add.how_requests, add.tool_calls) == (2, 5)


def test_trim_orders_by_tokens_when_friction_ties() -> None:
    targets = [
        candidates.Target("small", "skill", 1200),
        candidates.Target("large", "skill", 3000),
    ]
    found = candidates.rank(targets, {})
    assert names(found["trim"]) == ["large", "small"]


def test_thresholds_are_parameters() -> None:
    targets = [candidates.Target("x", "skill", 50)]
    assert candidates.rank(targets, {}, trim_at=10)["trim"][0].name == "x"


def test_cli_json_has_evidence_per_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    out = Io()
    code = cli_skills_candidates.run(["--json", str(FIXTURE)], out, demand=demand)
    assert code == 0
    data = json.loads(out.stdout.getvalue())["data"]["directions"]
    row = data["add"][0]
    assert {"friction", "how_skip", "tokens", "how_requests", "tool_calls"} <= set(row)
    assert data["reset"][0]["name"] == "s-reset"


def test_cli_text_and_failure() -> None:
    out = Io()
    assert cli_skills_candidates.run([str(FIXTURE)], out, demand=demand) == 0
    assert "add (2)" in out.stdout.getvalue()

    def broken() -> dict:
        raise OSError("bad store")

    err = Io()
    assert cli_skills_candidates.run([str(FIXTURE)], err, demand=broken) == 2
    assert "bad store" in err.stderr.getvalue()
