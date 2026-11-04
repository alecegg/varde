from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATTERNS = {
    "messages.jsonl": re.compile(r"['\"][^'\"]*messages\.jsonl[^'\"]*['\"]"),
    "deliveries.jsonl": re.compile(r"['\"][^'\"]*deliveries\.jsonl[^'\"]*['\"]"),
    "events.jsonl": re.compile(r"['\"][^'\"]*events\.jsonl[^'\"]*['\"]"),
    "cursors": re.compile(r"['\"][^'\"]*cursors[^'\"]*['\"]"),
    "index/": re.compile(
        r"['\"][^'\"]*[/\\]index(?:[/\\][^'\"]*)?['\"]"
        r"|/\s*['\"]index['\"]|(?:Path|PurePath|path\.join|os\.path\.join)"
        r"\([^)]*['\"]index['\"]"
    ),
    "watermark": re.compile(r"['\"][^'\"]*watermark[^'\"]*['\"]"),
    ".delivered.json": re.compile(
        r"['\"][^'\"]*\.delivered\.json[^'\"]*['\"]"
        r"|['\"][^'\"]*\.delivered['\"]\s*\+\s*['\"]\.json['\"]"
    ),
    "state.json": re.compile(r"['\"][^'\"]*state\.json[^'\"]*['\"]"),
}

EXEMPTIONS = {
    "workflow/src/varde_workflow/msg_status.py": (
        "Uses repository diagnostics and status_events(), not file I/O."
    ),
    "workflow/src/varde_workflow/commands/msg_soak.py": (
        "Consumes repository _below_watermark metadata."
    ),
    "runner/scripts/relay_e2e.py": "Standalone legacy-file E2E fixture.",
    "runner/scripts/mailbox_live_verify.py": (
        "Reads persisted messages from its isolated temporary verification store."
    ),
    "runner/scripts/live_role_inbox_verify.py": (
        "Drill over a temporary copy; names relay state.json paths to exclude."
    ),
    "runner/scripts/mail_flip_verify.py": (
        "Drill over a temporary copy; names relay state.json paths to exclude."
    ),
    "runner/scripts/queue_merge_verify.py": (
        "Verifies queue migration over isolated temporary copies of the store."
    ),
    "runner/src/varde_runner/relay_e2e.py": (
        "Dry-run E2E helper scans temporary artifacts only."
    ),
}


def _mail_path_sources() -> set[str]:
    offenders = set()
    for package in ROOT.iterdir():
        if package.name == "data":
            continue
        for source_root in (package / "src", package / "scripts"):
            if not source_root.is_dir():
                continue
            for source in source_root.rglob("*.py"):
                text = source.read_text(encoding="utf-8")
                if any(pattern.search(text) for pattern in AUDIT_PATTERNS.values()):
                    offenders.add(source.relative_to(ROOT).as_posix())
    return offenders


def test_mail_path_audit_matches_reasoned_exemptions() -> None:
    assert _mail_path_sources() == EXEMPTIONS.keys()


def test_mail_path_audit_matches_multiline_string_literal() -> None:
    sources = {
        "messages.jsonl": '"""legacy\nmessages.jsonl"""',
        "deliveries.jsonl": '"""legacy\ndeliveries.jsonl"""',
        "events.jsonl": '"""legacy\nevents.jsonl"""',
        "cursors": '"""legacy\ncursors"""',
        "index/": 'Path(\n    "some",\n    "index"\n)',
        "watermark": '"""legacy\nwatermark"""',
        ".delivered.json": '"""legacy\n.delivered.json"""',
        "state.json": '"""legacy\nstate.json"""',
    }

    assert all(AUDIT_PATTERNS[name].search(source) for name, source in sources.items())
    assert AUDIT_PATTERNS[".delivered.json"].search(
        'path = "legacy.delivered"\n    + ".json"'
    )
