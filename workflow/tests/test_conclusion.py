from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.errors import Conflict, Invalid, Locked, NotFound
from varde_workflow import conclusion
from varde_workflow.commands.conclude import run as run_conclude
from varde_workflow.conclusion import _mark_concluded_address


def _git_head(path: Path) -> tuple[Path, str]:
    path.mkdir()
    subprocess.run(  # noqa: S603 - Git metadata command in a temporary repo.
        ["git", "-C", str(path), "init", "-q"],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603 - Git metadata command in a temporary repo.
        [  # noqa: S607
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "review",
        ],
        check=True,
    )
    head = subprocess.check_output(  # noqa: S603 - Read the temp repo's head.
        ["git", "-C", str(path), "rev-parse", "HEAD"],  # noqa: S607
        text=True,
    ).strip()
    return path, head


@pytest.mark.parametrize(
    "relative,plan_bytes",
    [
        (
            Path("working/plans/bad-yaml/plan.md"),
            b"---\ntype: plan\nstatus: [\n---\n",
        ),
        (Path("working/plans/no-frontmatter/plan.md"), b"body without frontmatter\n"),
        (
            Path("working/elsewhere/outside/plan.md"),
            b"---\ntype: plan\nstatus: active\n---\n",
        ),
    ],
)
def test_missing_review_precedes_tolerant_plan_record_load(
    relative: Path,
    plan_bytes: bytes,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = tmp_path / relative
    plan.parent.mkdir(parents=True)
    plan.write_bytes(plan_bytes)

    result = run_conclude(
        SimpleNamespace(plan=plan.parent, merged=None, repo=tmp_path, json=True)
    )

    error = json.loads(capsys.readouterr().err)["data"]["error"]
    assert result == 1
    assert error["code"] == "review_invalid"
    assert str(plan.parent / "review.md") in error["message"]
    assert "No such file or directory" in error["message"]


@pytest.mark.parametrize("error_type", [Conflict, Locked, NotFound, Invalid])
def test_conclude_maps_writer_errors(
    error_type: type[Exception],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, head = _git_head(tmp_path / "repo")
    plan = tmp_path / "working" / "plans" / "demo"
    plan.mkdir(parents=True)
    (plan / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n", encoding="utf-8"
    )
    (plan / "plan.md").write_text(
        "---\nid: demo\ntype: plan\nstatus: active\n---\n", encoding="utf-8"
    )

    def fail(*args, **kwargs):
        raise error_type("forced writer error")

    class FailingRepository:
        def set_plan_status(self, *args, **kwargs):
            return fail(*args, **kwargs)

    monkeypatch.setattr(
        conclusion,
        "_load_plan_record",
        lambda _path: (FailingRepository(), SimpleNamespace()),
    )
    result = run_conclude(Namespace(plan=plan, merged=head, repo=repo, json=True))

    error = json.loads(capsys.readouterr().err)["data"]["error"]
    expected_code = (
        "plan_locked"
        if error_type is Locked
        else "plan_conflict"
        if error_type is Conflict
        else "review_invalid"
    )
    assert result == 1
    assert error["code"] == expected_code
    assert "no fix guidance is registered" not in error.get("fix", {}).get("reason", "")
    if error_type in (Conflict, Locked):
        assert error["message"] == (
            "plan is locked by another operation; retry shortly"
            if error_type is Locked
            else "plan changed while writing; reload it and retry"
        )


def test_conclusion_retires_plan_address_but_not_slot_address(tmp_path) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    slots = tmp_path / ".cache" / "inbox" / "slots"
    slots.mkdir(parents=True)
    (slots / "orchestrator-1.json").write_text(
        json.dumps(
            {
                "slot": "orchestrator-1",
                "aliases": ["slot-plan"],
                "current_address": "orchestrator-1",
            }
        ),
        encoding="utf-8",
    )

    _mark_concluded_address(plans / "plan-a", "plan-a")
    _mark_concluded_address(plans / "slot-plan", "slot-plan")
    _mark_concluded_address(plans / "orchestrator-1", "orchestrator-1")

    state_path = tmp_path / ".cache" / "inbox" / "relay" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    retired = state["retired"]
    assert "plan-a" in retired
    assert "slot-plan" not in retired
    assert "orchestrator-1" not in retired
