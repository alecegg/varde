"""Pure decisions and text for the `varde setup` repo-map step."""

from __future__ import annotations

START = "<!-- varde-map:start -->"
END = "<!-- varde-map:end -->"
MAX_MODULES = 20
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".scala",
        ".sh",
    }
)
SKIPPED_FOLDERS = frozenset(
    {
        "vendor",
        "third_party",
        "node_modules",
        "build",
        "dist",
        "target",
        "out",
        "docs",
        "doc",
        "test",
        "tests",
        "__tests__",
        "spec",
        "specs",
    }
)


BODY = (
    "Read `docs/repo-map/README.md` first, then the module pack for the folder "
    "you edit.\n"
    "Check freshness with `varde map packs status --check`; refresh with "
    "`varde map packs build --stale`."
)


def block_text() -> str:
    return f"{START}\n{BODY}\n{END}"


def merge_block(existing: str | None) -> str:
    block = block_text()
    if existing is None:
        return block + "\n"
    start = existing.find(START)
    end = existing.find(END, start + len(START)) if start >= 0 else -1
    if end >= 0:
        return existing[:start] + block + existing[end + len(END) :]
    return existing.rstrip("\n") + "\n\n" + block + "\n"


def default_modules(tracked: list[str]) -> list[str]:
    found: set[str] = set()
    for path in tracked:
        folder, sep, rest = path.partition("/")
        if not sep or folder.startswith(".") or folder in SKIPPED_FOLDERS:
            continue
        if "." + rest.rsplit(".", 1)[-1] in SOURCE_SUFFIXES:
            found.add(folder)
    return sorted(found)[:MAX_MODULES]


def plan_step(
    is_main_checkout: bool, readme_exists: bool, block_present: bool
) -> list[str]:
    if not is_main_checkout:
        return []
    actions = ["edit-agents-md"]
    if not readme_exists:
        actions.append("build-packs")
    return actions
