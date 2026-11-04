from __future__ import annotations

from varde.cli import _discover_modules, _recorded_route
from varde.help.route_snapshots import ROUTE_HELP
from varde.router import resolve
from varde_learn.loop.guardrails import load_registry


def test_cli_step_guardrails_match_router_and_recorded_commands() -> None:
    modules = _discover_modules()
    entries = [entry for entry in load_registry() if entry["kind"] == "cli-step"]

    assert len(entries) == 15
    for entry in entries:
        command = entry.get("command")
        assert command is not None, entry["id"]
        words = command.split()
        resolved = resolve([*words, "registry-tail"])
        assert resolved is not None, command
        route, _ = resolved
        module = modules.get(route.module)
        module_help = getattr(module, "help", None) if module else None
        help_text = (
            ROUTE_HELP.get(route.path, "")
            if route.path == ("setup",)
            else module_help(" ".join(route.path))
            if module_help
            else ""
        )

        recorded = _recorded_route(
            route.path, [*words, "registry-tail"], help_text, module_help
        )
        assert recorded == command, command
        assert words[len(recorded.split()) :] == [], command
        assert [*words, "registry-tail"][len(recorded.split()) :] == [
            "registry-tail"
        ], command
