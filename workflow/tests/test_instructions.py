from pathlib import Path

from varde_core.constants import HOW_NOTE
from varde_workflow.blocks import has_managed_block, install_block, remove_blocks
from varde_workflow.commands.instructions import (
    RoleCaps,
    render_block,
    resolved_caps,
    unique_targets,
)


def test_install_and_remove_managed_block() -> None:
    block = b"<!-- varde:start -->\nmanaged\n<!-- varde:end -->"
    original = b"existing text\n"
    installed = install_block(original, block)

    assert installed == original + b"\n\n" + block + b"\n"
    assert (
        install_block(installed, block.replace(b"managed", b"updated"))
        == original + b"\n\n" + block.replace(b"managed", b"updated") + b"\n"
    )
    assert remove_blocks(installed) == original


def test_multiple_blocks_keep_only_first_on_update() -> None:
    block = b"<!-- varde:start -->new<!-- varde:end -->"
    content = (
        b"a\n\n<!-- varde:start -->old<!-- varde:end -->\nb\n"
        b"<!-- varde:start -->older<!-- varde:end -->\nc"
    )

    assert install_block(content, block) == b"a\n\n" + block + b"\nb\n\nc"
    assert remove_blocks(content) == b"a\n\n\nb\n\nc"


def test_has_managed_block(tmp_path: Path) -> None:
    path = tmp_path / "instructions.md"
    assert not has_managed_block(path)
    path.write_bytes(b"<!-- varde:start -->\nmanaged\n<!-- varde:end -->")
    assert has_managed_block(path)


def test_learn_block_explains_how_topics() -> None:
    block = render_block(RoleCaps(), ["learn"])

    assert HOW_NOTE in block
    assert "`varde learn how <skill>`" in block
    assert "`varde learn how <skill> <step>`" in block
    assert HOW_NOTE not in render_block(RoleCaps(), ["toz"])


def test_caps_use_defaults_and_validate_raw_config(capsys) -> None:
    assert resolved_caps({}) == RoleCaps()
    assert resolved_caps({"builders": 7, "planners": -1}).builders == 7
    assert "planners ignored" in capsys.readouterr().err


def test_rendered_sections_include_requested_sections_in_order() -> None:
    block = render_block(RoleCaps(builders=3), ["orchestration", "toz", "learn"])

    assert block.startswith("<!-- varde:start -->\n")
    assert block.endswith("<!-- varde:end -->")
    assert "Role caps per orchestrator: 3 builders" in block
    assert "Main agent status format: see varde-swarm `references/status.md`" in block
    assert "Main agent status format: details:" not in block
    assert "or `varde-swarm` for several plans" not in block
    assert "use `varde-swarm` only when the user asks" in block
    assert "hand-written part of the session notes" in block
    assert "tidy it when nudged" in block
    assert "<session notes path from the session-start hook>" in block
    assert block.index("## varde-toz (tool-output-zone)") < block.index(
        "<!-- varde-learn:start -->"
    )
    plain = render_block(RoleCaps(), ["orchestration"])
    assert "## varde-toz" not in plain
    assert "<!-- varde-learn:start -->" not in plain


def test_unique_targets_accepts_cli_strings(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"

    assert unique_targets([str(target)]) == [target]
