"""Hooks section for ``varde setup doctor``."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from varde_toz.doctor import DoctorEntry, DoctorSection

from . import HARNESSES, OPENCODE_UNSUPPORTED, is_unedited, plugin_path
from .codex_trust import query_hooks, untrusted_varde_hooks
from .json_hooks import EVENTS, find_entries, stable_varde_path


def doctor_section() -> DoctorSection:
    home = Path(os.environ.get("HOME", ""))
    exe = stable_varde_path(home)
    entries: list[DoctorEntry] = []
    for harness in HARNESSES:
        if harness in ("opencode", "pi"):
            path = plugin_path(harness, home)
            state = plugin_state(path)
            entries.append(doctor_entry(harness, "plugin", state, path))
        else:
            path = home / (
                ".claude/settings.json" if harness == "claude" else ".codex/hooks.json"
            )
            entries.extend(json_entries(harness, path, exe))
            if harness == "codex":
                try:
                    cwd = Path.cwd()
                except OSError:
                    cwd = None
                trust = query_hooks(cwd) if cwd is not None else None
                if trust is None:
                    if shutil.which("codex") is not None:
                        entries.append(
                            DoctorEntry(
                                "hook codex trust status: unknown "
                                "(Codex app-server query failed)",
                                {
                                    "harness": "codex",
                                    "target": "trust-status",
                                    "state": "unknown",
                                    "path": str(path),
                                },
                            )
                        )
                else:
                    for hook in untrusted_varde_hooks(trust, Path.cwd()):
                        target = hook["key"].split(":", 1)[0].replace("_", "-")
                        state = hook["state"]
                        fix = "open codex and approve the hooks in /hooks"
                        entries.append(
                            DoctorEntry(
                                f"hook codex {target}: {state} ({hook['key']}); "
                                f"fix: {fix}",
                                {
                                    "harness": "codex",
                                    "target": target,
                                    "state": state,
                                    "path": str(path),
                                    "fix": fix,
                                },
                            )
                        )
        if harness == "opencode":
            entries.append(
                DoctorEntry(
                    "hook opencode user-prompt-submit: unsupported "
                    f"({OPENCODE_UNSUPPORTED})",
                    {
                        "harness": "opencode",
                        "target": "user-prompt-submit",
                        "state": "unsupported",
                        "reason": OPENCODE_UNSUPPORTED,
                        "path": str(path),
                    },
                )
            )
    return DoctorSection("hooks", entries)


def plugin_state(path: Path) -> str:
    try:
        return "current" if is_unedited(path.read_text(encoding="utf-8")) else "edited"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "edited"


def json_entries(harness: str, path: Path, exe: str) -> list[DoctorEntry]:
    try:
        doc: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or (
            "hooks" in doc and not isinstance(doc["hooks"], dict)
        ):
            doc = None
    except FileNotFoundError:
        doc = {}
    except OSError, ValueError, RecursionError:
        doc = None
    result = []
    for event in EVENTS:
        found = find_entries(doc, event, harness, exe) if doc is not None else None
        state = (
            "edited"
            if found is None
            else "missing"
            if not found
            else "current"
            if len(found) == 1 and found[0].unified
            else "edited"
        )
        result.append(doctor_entry(harness, event.key, state, path))
    return result


def doctor_entry(harness: str, target: str, state: str, path: Path) -> DoctorEntry:
    value: dict[str, str] = {
        "harness": harness,
        "target": target,
        "state": state,
        "path": str(path),
    }
    line = f"hook {harness} {target}: {state} ({path})"
    if state != "current":
        fix = f"varde setup hooks install --harness {harness}" + (
            " --force" if state == "edited" else ""
        )
        value["fix"] = fix
        line += f"; fix: {fix}"
    return DoctorEntry(line, value)
