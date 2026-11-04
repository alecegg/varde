"""Block type for changed files: file-tree."""

from varde_learn.docs.pages.blocks.change import CHANGE_FIELDS, change_faults
from varde_learn.docs.pages.blocks.rules import (
    Fault,
    check_keys,
    duplicates,
    str_field,
    tables,
    tables_fault,
)
from varde_learn.docs.pages.blocks.spec import BlockSpec


def path_faults(path: object, where: str) -> list[Fault]:
    """A path is `a/b/c`: no empty, `.` or `..` part, no leading or trailing slash."""
    if not isinstance(path, str) or not path.strip():
        return [Fault("type", f"{where}: 'path' must be a non-empty string")]
    if any(part in ("", ".", "..") for part in path.split("/")):
        return [
            Fault(
                "path",
                f"{where}: path '{path}' needs plain segments "
                "(no leading or trailing slash, empty, '.' or '..' part)",
            )
        ]
    return []


def _folder_faults(paths: list[str]) -> list[Fault]:
    """A file and a folder cannot share a path (`a` and `a/b`)."""
    folders = {
        "/".join(p.split("/")[:n]) for p in paths for n in range(1, len(p.split("/")))
    }
    return [
        Fault("path", f"file-tree: '{p}' is both a file and a folder")
        for p in sorted(set(paths) & folders)
    ]


def _entry_faults(entry: dict[str, object], where: str) -> list[Fault]:
    faults = check_keys(entry, {"path"}, {"change", "was", "note", "role"}, where)
    faults += path_faults(entry.get("path"), where) if "path" in entry else []
    faults += str_field(entry, "note", where) + str_field(entry, "role", where)
    return faults + change_faults(entry, where)


def _collapse_faults(data: dict[str, object]) -> list[Fault]:
    collapse = data.get("collapse")
    if "collapse" not in data:
        return []
    if isinstance(collapse, int) and not isinstance(collapse, bool) and collapse >= 0:
        return []
    return [Fault("type", "file-tree: 'collapse' must be a whole number, 0 or more")]


def validate_file_tree(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"entries"}, {"title", "collapse"}, "file-tree")
    faults += str_field(data, "title", "file-tree") + _collapse_faults(data)
    faults += tables_fault(data, "entries", "file-tree")
    entries = tables(data, "entries", "file-tree")
    for n, entry in enumerate(entries, 1):
        faults += _entry_faults(entry, f"file-tree.entries[{n}]")
    paths = [str(e["path"]) for e in entries if isinstance(e.get("path"), str)]
    faults += [
        Fault("duplicate-path", f"file-tree: path '{p}' appears more than once")
        for p in duplicates(paths)
    ]
    return faults + _folder_faults(paths)


FILE_TREE = BlockSpec(
    "file-tree",
    "Changed files as a folder tree with change markers, notes and link to code",
    (
        "title     optional heading",
        "entries   list of tables, one per file; a path appears once",
        "  path    `dir/file.ext`, no leading slash",
        "  note    optional short text shown on the same row",
        "  role    optional label such as test or config",
        *(f"  {line}" for line in CHANGE_FIELDS),
        "          a renamed file sits at its new path; `was` is the old path",
        "collapse  optional: close folders deeper than this many levels (default none)",
        "A file whose path ends with the title of a `code` block links to that block.",
    ),
    r"""file-tree = file-tree(
  title: "Changed files",
  collapse: 2,
  entries: [
    {"path": "src/queue.py", "change": "modified", "note": "push returns the id"},
    {"path": "src/retry.py", "change": "added"},
    {"path": "src/backoff.py", "change": "renamed", "was": "src/wait.py"},
    {"path": "tests/test_queue.py", "change": "modified", "role": "test"},
  ],
)
""",
    validate_file_tree,
)
