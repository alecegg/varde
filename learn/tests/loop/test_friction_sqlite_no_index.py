"""With friction on sqlite the legacy ``learn.db`` index is never created or opened."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_data.friction import open_friction
from varde_data.learn_store_mode import exclusive_store_lock, flip_domain_locked
from varde_learn.loop.cli_friction_read import run_list


def _forbid_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SqliteFrictionIndex was opened")

    monkeypatch.setattr(
        "varde_data.backends.sqlite.friction.SqliteFrictionIndex.__init__", refuse
    )


def test_friction_commands_do_not_touch_learn_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "learn"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    with exclusive_store_lock(store):
        flip_domain_locked(store, "friction", "sqlite")
    _forbid_index(monkeypatch)

    repository = open_friction(store)
    from varde_data.repos.friction import FrictionAddRequest

    repository.add(FrictionAddRequest("Slow", "pytest", "again", "/work", "/repo"))
    output = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())

    assert run_list({"json": True}, output) == 0
    assert json.loads(output.stdout.getvalue())["data"]["items"][0]["slug"] == "slow"
    assert not (store / "learn.db").exists()
    assert not (store / "friction.jsonl").exists()


def test_files_mode_still_uses_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = Path(__file__).parent / "golden" / "friction" / "friction.jsonl"
    shutil.copyfile(golden, tmp_path / "friction.jsonl")

    open_friction(tmp_path).list_items()

    assert (tmp_path / "learn.db").exists()
