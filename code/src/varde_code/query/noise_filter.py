"""Path and content filters for generated or low-value navigation results."""

from __future__ import annotations

from pathlib import Path

from varde_code.parse import language_for_path

SCAFFOLD_DIR_COMPONENTS = frozenset({"templates", "template"})
EXCLUDED_DIR_COMPONENTS = frozenset(
    {
        "target",
        "node_modules",
        "dist",
        "build",
        "vendor",
        "third_party",
        "third-party",
        "bower_components",
        ".next",
        ".nuxt",
        "grammars",
    }
)
EXCLUDED_DIR_SEQUENCES = (
    ("priv", "static"),
    ("alembic", "versions"),
    ("migrations", "versions"),
)
GENERATED_FILE_SUFFIXES = (
    ".min.js",
    ".min.mjs",
    ".min.cjs",
    ".min.css",
    ".bundle.js",
    ".bundle.mjs",
    ".pb.go",
    ".gen.go",
    ".gen.ts",
    ".gen.tsx",
    ".gen.js",
    ".gen.mjs",
    ".gen.cjs",
)
FRONTEND_ASSET_EXTENSIONS = frozenset(
    {
        "js",
        "mjs",
        "cjs",
        "jsx",
        "ts",
        "tsx",
        "css",
        "scss",
        "sass",
        "less",
        "vue",
        "svelte",
    }
)


def _parts(path: str) -> list[str]:
    return [part for part in Path(path).parts if part not in ("/", "\\")]


def is_non_source_path(path: str) -> bool:
    return language_for_path(Path(path)) is None


def is_scaffold_template_path(path: str) -> bool:
    return any(part in SCAFFOLD_DIR_COMPONENTS for part in _parts(path))


def is_frontend_asset_path(path: str) -> bool:
    parts = _parts(path)
    return (
        "assets" in parts
        and Path(path).suffix.lower().lstrip(".") in FRONTEND_ASSET_EXTENSIONS
    )


def is_generated_or_vendored_path(path: str) -> bool:
    parts = _parts(path)
    if any(
        part in EXCLUDED_DIR_COMPONENTS or part.endswith(("_fixture", "_fixtures"))
        for part in parts
    ):
        return True
    if any(
        tuple(parts[i : i + len(seq)]) == seq
        for seq in EXCLUDED_DIR_SEQUENCES
        for i in range(len(parts))
    ):
        return True
    name = Path(path).name.lower()
    return any(name.endswith(suffix) for suffix in GENERATED_FILE_SUFFIXES)


def is_minified_source(source: str) -> bool:
    if any(
        "Code generated" in line and "DO NOT EDIT" in line
        for line in source.splitlines()[:5]
    ):
        return True
    lines = source.splitlines()
    if not lines:
        return False
    long_count = sum(len(line) >= 500 for line in lines)
    return max(map(len, lines)) >= 2000 and long_count / len(lines) >= 0.5
