from pathlib import Path

from varde_learn.loop.guardrails import check_owners, load_registry


def test_loads_package_registry_and_validates_owners() -> None:
    registry = load_registry()
    check_owners(registry, Path(__file__).resolve().parents[2])
    assert {entry["kind"] for entry in registry} == {
        "hook",
        "gate",
        "cli-check",
        "cli-step",
    }
    hooks = {entry["id"]: entry for entry in registry if entry["kind"] == "hook"}
    assert hooks["hook-pre-tool-install-guard"]["owner"] == (
        "app/src/varde/glue/tool_install_guard.py"
    )
    assert hooks["hook-pre-tool-worktree-prune"]["owner"] == (
        "app/src/varde/glue/worktree_prune_guard.py"
    )
    assert hooks["hook-stop-inbox-block"]["owner"] == "app/src/varde/glue/hook.py"
