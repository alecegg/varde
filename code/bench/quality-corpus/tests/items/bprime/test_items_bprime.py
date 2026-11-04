"""Structure checks for the category (b') agent-style refactor pairs.

Behaviour equivalence of the two sides is checked by tools/behaviour_runner.py
and the blind-input rules by tools/hygiene.py; this module checks the data
shape and runs both tools over the items.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import behaviour_runner
import pytest

ROOT = Path(__file__).resolve().parents[3]
ITEMS = ROOT / "items" / "_bprime"
RUNNER = ROOT / "tools" / "behaviour_runner.py"
HYGIENE = ROOT / "tools" / "hygiene.py"
LANGUAGES = ("python", "typescript", "java", "csharp", "go", "rust", "cpp")
SUFFIX = {
    "python": ".py",
    "typescript": ".ts",
    "java": ".java",
    "csharp": ".cs",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
}
PROBE_ARGUMENTS = {"go": ("version",)}
OPAQUE_ID = re.compile(r"[0-9a-f]{24,64}")
PAIR_FIELDS = {
    "pair_id",
    "pair_group_id",
    "left_id",
    "right_id",
    "left",
    "right",
    "left_role",
    "right_role",
}


def pair_directories(language: str) -> list[Path]:
    return sorted(path for path in (ITEMS / language).iterdir() if path.is_dir())


def read_pair(directory: Path) -> dict:
    return json.loads((directory / "pair.json").read_text())


def hygiene_command(directory: Path) -> list[str]:
    return [sys.executable, str(HYGIENE), "--items", str(directory), "--check"]


def behaviour_command(language: str) -> list[str]:
    return [sys.executable, str(RUNNER), "--items", str(ITEMS / language), "--check"]


def command_failure(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - Runs the fixture's selected compiler command.
    return "" if result.returncode == 0 else result.stdout + result.stderr


def toolchain_skip_reason(language: str) -> str | None:
    suffix = SUFFIX[language]
    commands = behaviour_runner.available_commands(suffix)
    if commands is None:
        return behaviour_runner.unavailable_reason(suffix)
    arguments = PROBE_ARGUMENTS.get(language, ("--version",))
    probe = subprocess.run(  # noqa: S603 - Probes availability of the fixture's compiler.
        [commands[0], *arguments], check=False, capture_output=True, text=True
    )
    if probe.returncode:
        details = probe.stderr.strip() or probe.stdout.strip()
        return f"{commands[0]} is unusable: {details}"
    return None


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_well_formed_pairs_per_language(language: str) -> None:
    suffix = SUFFIX[language]
    directories = pair_directories(language)
    if len(directories) != 2:
        pytest.fail(f"{language}: expected 2 pairs, found {len(directories)}")
    for directory in directories:
        label = f"{language}/{directory.name}"
        pair = read_pair(directory)
        assert set(pair) >= PAIR_FIELDS, label
        assert pair["pair_id"] == directory.name, label
        for field in ("pair_id", "pair_group_id", "left_id", "right_id"):
            assert OPAQUE_ID.fullmatch(pair[field]), f"{label}: {field} not opaque"
        assert pair["left"] == f"a{suffix}", label
        assert pair["right"] == f"b{suffix}", label
        assert pair["left_role"] == "before", label
        assert pair["right_role"] == "after", label
        left = directory / pair["left"]
        right = directory / pair["right"]
        assert left.is_file() and right.is_file(), label
        assert left.read_bytes() != right.read_bytes(), label
        tests = sorted(directory.glob("behaviour_test.*"))
        assert [path.name for path in tests] == [f"behaviour_test{suffix}"], label
        manifest = tomllib.loads((directory / "manifest.toml").read_text())
        assert manifest["category"] == "b'", label
        assert manifest["language"] == language, label
        assert manifest["split"] == "dev", label
        assert manifest["source"] == "authored", label
        assert manifest["provenance"] == "authored", label
        assert manifest["pair_id"] == pair["pair_id"], label
        assert manifest["pair_group_id"] == pair["pair_group_id"], label
        assert (directory / "task.txt").read_text().strip(), label
        output = command_failure(hygiene_command(directory))
        assert output == "", f"{label}: {output}"


def test_pairs_are_complete_and_unique() -> None:
    identifiers = []
    groups = []
    for language in LANGUAGES:
        for directory in pair_directories(language):
            pair = read_pair(directory)
            identifiers.append(pair["pair_id"])
            groups.append(pair["pair_group_id"])
    assert len(identifiers) == 2 * len(LANGUAGES)
    assert len(set(identifiers)) == len(identifiers)
    assert len(set(groups)) == len(groups)


@pytest.mark.parametrize("language", LANGUAGES)
def test_declared_versions_pass_the_shared_behaviour_test(language: str) -> None:
    reason = toolchain_skip_reason(language)
    if reason is not None:
        pytest.skip(reason)
    output = command_failure(behaviour_command(language))
    assert output == "", f"{language}: {output}"
