from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.messages import Delivery, NewMessage
from varde_runner.messages import recipient_matches_address
from varde_runner.varde_cli import VardeCLI
from varde_runner.web.cache import InboxStoreCache


def test_recipient_matches_registered_aliases() -> None:
    bindings = [{"slot": "orchestrator", "aliases": ["orchestrator-3"]}]
    assert recipient_matches_address("orchestrator-3", "orchestrator", bindings)
    assert recipient_matches_address("orchestrator", "orchestrator-3", bindings)
    assert not recipient_matches_address("other", "orchestrator", bindings)


def test_runner_and_cli_share_alias_unread_and_concluded_state(tmp_path: Path) -> None:
    working = tmp_path / "working"
    inbox = working / ".cache" / "inbox"
    slots = inbox / "slots"
    slots.mkdir(parents=True)
    (slots / "orchestrator.json").write_text(
        json.dumps({"slot": "orchestrator", "aliases": ["orchestrator-3"]}),
        encoding="utf-8",
    )
    (inbox / "relay").mkdir()
    (inbox / "relay" / "state.json").write_text(
        json.dumps({"concluded_addresses": ["finished"]}), encoding="utf-8"
    )
    repository = open_data(working, DataConfig()).messages
    first = repository.append(NewMessage("main", "orchestrator", "info", "unread"))
    repository.append(NewMessage("main", "finished", "info", "done"))
    repository.record_delivery(
        Delivery(first.id or "", "orchestrator-3", "s", "cli", "delivered", "now")
    )
    repository.ack("orchestrator-3", first.id or "")
    unread = repository.append(
        NewMessage("main", "orchestrator-3", "info", "still unread")
    )

    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(working)})
    cache = InboxStoreCache(working)

    cli_all = {row["id"] for row in cli.read_messages()}
    runner_all = {row["id"] for row in cache.read_messages()}
    assert cli_all == runner_all
    repo = Path(__file__).resolve().parents[2]
    runner_unread = cache.repository.peek_unread("orchestrator-3")
    uv = shutil.which("uv")
    assert uv is not None
    result = subprocess.run(  # noqa: S603 - fixed CLI and fixture paths.
        [
            uv,
            "run",
            "--project",
            str(repo / "app"),
            "varde",
            "msg",
            "read",
            "--as",
            "orchestrator-3",
            "--json",
        ],
        cwd=repo,
        env={**os.environ, "VARDE_WORKING_DIR": str(working)},
        capture_output=True,
        check=True,
        text=True,
    )
    cli_unread = json.loads(result.stdout)["data"]["messages"]
    assert [item["id"] for item in cli_unread] == [row.id for row in runner_unread]
    assert [row.id for row in runner_unread] == [unread.id]
    assert cache.read().concluded_addresses == {"finished"}
    assert cli.read_concluded_addresses() == ["finished"]
