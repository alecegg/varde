"""Project discovery for `varde design survey`: paths and file text in, a Survey out.

Pure: the filesystem walk lives in survey_walk.py. Nothing here guesses a design
system into existence; an empty dimension stays empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .tokens import collect_tokens

MAX_READ_BYTES = 512 * 1024
MAX_PAGES_READ = 200
SHEET_EXTS = (".css", ".scss", ".pcss", ".less")
PAGE_EXTS = (".html", ".tsx", ".jsx", ".vue", ".svelte", ".astro")
COMPONENT_DIRS = ("components", "component", "ui", "widgets")
ROUTE_DIRS = ("pages", "routes", "app", "views")
DOC_NAMES = ("DESIGN.md", "Design.md", "design.md")
DOC_DIRS = ("", ".agents/context", "docs")
SIDECARS = (".impeccable/design.json", "DESIGN.json")
STYLE_DOC_STEMS = ("styleguide", "tokens", "uistandards", "designsystem")
THEME_CONFIG = re.compile(r"(tailwind|uno|windi|panda)\.config\.(js|cjs|mjs|ts)")
PROJECT_MARKERS = (".git", "package.json", ".impeccable")
STATE_WORDS = (":hover", ":focus", ":disabled", "aria-", "loading", "empty", "error")
FRAMEWORKS = {
    "react": "react",
    "next": "next",
    "vue": "vue",
    "nuxt": "nuxt",
    "svelte": "svelte",
    "@sveltejs/kit": "sveltekit",
    "astro": "astro",
    "solid-js": "solid",
    "@angular/core": "angular",
}
CSS_IN_JS = (
    "styled-components",
    "@emotion/react",
    "@stitches/react",
    "@vanilla-extract/css",
)


@dataclass(frozen=True)
class Survey:
    token_sheets: list[tuple[str, int]] = field(default_factory=list)
    token_total: int = 0
    token_json: list[str] = field(default_factory=list)
    theme_configs: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    component_dirs: list[str] = field(default_factory=list)
    pages: list[tuple[str, int]] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    styling: str = "none"
    docs: list[str] = field(default_factory=list)
    truncated: bool = False


def project_root(start: str, dirs_with_markers: set[str]) -> str:
    """Nearest directory at or above start that holds a project marker.

    dirs_with_markers holds directories (posix, '' for the top) that contain
    .git, package.json or .impeccable. A nested package stops the climb at its
    own directory, so it does not inherit a parent's design doc. Falls back to start.
    """
    current = PurePosixPath(start)
    while True:
        text = "" if str(current) == "." else str(current)
        if text in dirs_with_markers:
            return text
        if text == "":
            return "" if start in ("", ".") else start
        current = current.parent


def _ext(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def _in_dirs(path: str, names: tuple[str, ...]) -> bool:
    return any(part.lower() in names for part in _parts(path)[:-1])


def find_design_docs(paths: list[str]) -> list[str]:
    """Design docs in search order: DESIGN.md variants, sidecars, then style docs."""
    present = set(paths)
    docs = [
        f"{folder}/{name}".lstrip("/")
        for folder in DOC_DIRS
        for name in DOC_NAMES
        if f"{folder}/{name}".lstrip("/") in present
    ]
    docs += [side for side in SIDECARS if side in present]
    for path in sorted(paths):
        stem = re.sub(r"[\s_-]", "", PurePosixPath(path).stem.lower())
        if _ext(path) == ".md" and stem in STYLE_DOC_STEMS and path not in docs:
            docs.append(path)
    return docs


def _is_token_json(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name.endswith(".json") and PurePosixPath(name).stem.endswith("tokens")


def is_sheet(path: str) -> bool:
    return _ext(path) in SHEET_EXTS


def is_page(path: str) -> bool:
    if _in_dirs(path, COMPONENT_DIRS) or _ext(path) not in PAGE_EXTS:
        return False
    return _ext(path) == ".html" or _in_dirs(path, ROUTE_DIRS)


def files_to_read(paths: list[str], sizes: dict[str, int]) -> list[str]:
    """Paths whose text the survey needs, within the size and page caps."""
    pages = [p for p in paths if is_page(p)][:MAX_PAGES_READ]
    wanted = [
        p
        for p in paths
        if is_sheet(p)
        or PurePosixPath(p).name == "package.json"
        or THEME_CONFIG.fullmatch(PurePosixPath(p).name)
    ]
    return [p for p in wanted + pages if sizes.get(p, 0) <= MAX_READ_BYTES]


def _dependencies(package_json: str) -> set[str]:
    try:
        data = json.loads(package_json)
    except ValueError:
        return set()
    if not isinstance(data, dict):
        return set()
    found: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            found.update(section)
    return found


def detect_frameworks(paths: list[str], deps: set[str]) -> list[str]:
    names = {name for dep, name in FRAMEWORKS.items() if dep in deps}
    for ext, name in ((".vue", "vue"), (".svelte", "svelte"), (".astro", "astro")):
        if any(_ext(p) == ext for p in paths):
            names.add(name)
    return sorted(names)


def detect_styling(paths: list[str], deps: set[str], has_theme_config: bool) -> str:
    if "tailwindcss" in deps or has_theme_config:
        return "utility classes (tailwind-style config)"
    if any(dep in deps for dep in CSS_IN_JS):
        return "css-in-js"
    if any(p.lower().endswith(".module.css") for p in paths):
        return "css modules"
    if any(is_sheet(p) for p in paths) or any(_ext(p) == ".html" for p in paths):
        return "plain css"
    return "none"


def page_score(text: str) -> int:
    """Token uses plus 3 per distinct state word (hover, focus, error, ...)."""
    states = sum(1 for word in STATE_WORDS if word in text.lower())
    return text.count("var(--") + 3 * states


def rank_pages(paths: list[str], texts: dict[str, str]) -> list[tuple[str, int]]:
    scored = [(p, page_score(texts[p])) for p in paths if is_page(p) and p in texts]
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def _component_files(paths: list[str]) -> list[str]:
    return [p for p in paths if _in_dirs(p, COMPONENT_DIRS) and _ext(p) in PAGE_EXTS]


def _component_dirs(files: list[str]) -> list[str]:
    return sorted({str(PurePosixPath(p).parent) for p in files})


def build_survey(
    paths: list[str], texts: dict[str, str], truncated: bool = False
) -> Survey:
    """Survey of a project from its file paths and the text of files_to_read."""
    sheets = [p for p in paths if is_sheet(p) and p in texts]
    per_sheet = [(p, len(collect_tokens([texts[p]]))) for p in sheets]
    token_sheets = sorted((item for item in per_sheet if item[1] > 0), key=_by_count)
    deps: set[str] = set()
    for path in paths:
        if PurePosixPath(path).name == "package.json" and path in texts:
            deps |= _dependencies(texts[path])
    configs = [
        p
        for p in paths
        if THEME_CONFIG.fullmatch(PurePosixPath(p).name)
        and "theme" in texts.get(p, "").lower()
    ]
    comp_files = _component_files(paths)
    return Survey(
        token_sheets=token_sheets,
        token_total=len(collect_tokens(texts[p] for p in sheets)),
        token_json=sorted(p for p in paths if _is_token_json(p)),
        theme_configs=configs,
        components=sorted({PurePosixPath(p).stem for p in comp_files}),
        component_dirs=_component_dirs(comp_files),
        pages=rank_pages(paths, texts),
        frameworks=detect_frameworks(paths, deps),
        styling=detect_styling(paths, deps, bool(configs)),
        docs=find_design_docs(paths),
        truncated=truncated,
    )


def _by_count(item: tuple[str, int]) -> tuple[int, str]:
    return (-item[1], item[0])
