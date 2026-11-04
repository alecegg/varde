"""Keep persistent store filenames inside the data module as domains migrate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE_NAMES = (
    "messages.jsonl",
    "deliveries.jsonl",
    "cursors",
    "delivered.json",
    ".messages.lock",
    "friction.jsonl",
    "learn.db",
    "queue-order.json",
    "comments.jsonl",
    "events.jsonl",
    "relay/state.json",
    "bindings/",
    "addresses/",
    "slots/",
    "workitems.sqlite3",
    "decisions.sqlite3",
    "decisions.audit.jsonl",
)

# This is the committed migration baseline. Each domain step removes paths as it
# moves its store references into varde-data.
ALLOWED_FILES = frozenset(
    {
        "runner/src/varde_runner/web/queue.py",
        # Per-document comments sidecar (user-reviewable file), not a data store.
        "learn/src/varde_learn/docs/pages/comments.py",
        # Serve watches the same comments sidecars and exposes the queue-order
        # file as an API resource; it owns no store of its own.
        "serve/src/varde_serve/events/watchers.py",
        "serve/src/varde_serve/api/read.py",
    }
)


def _store_name_files() -> set[str]:
    offenders = set()
    for package in ROOT.iterdir():
        source_root = package / "src"
        if not source_root.is_dir():
            continue
        for source in source_root.rglob("*.py"):
            if package.name == "data":
                continue
            text = source.read_text(encoding="utf-8")
            if any(name in text for name in STORE_NAMES):
                offenders.add(source.relative_to(ROOT).as_posix())
    return offenders


def test_store_file_names_are_confined_to_data_or_baseline() -> None:
    assert _store_name_files() == ALLOWED_FILES
