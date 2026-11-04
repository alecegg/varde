"""HTML for the file-tree block: folders as `<details>`, files with change badges.

`fold` turns the flat path list into a nested structure; the renderers are pure
string builders. Single-child folder chains show as one row (`a/b/c`). A file whose
path matches the title of a `code` block links to it: the row carries a marker
that `link_files` turns into `<a href="#id">` once the page knows its blocks.
"""

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from varde_learn.docs.pages.blocks_render.change import (
    GLYPHS,
    change_badge,
    change_name,
    change_of,
)
from varde_learn.docs.pages.blocks_render.common import as_list, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

MAX_INDENT_LEVEL = 5  # folders nested deeper than this stop indenting
CODE_TITLE = re.compile(
    r'<figure class="vb code [^"]*"[^>]*><figcaption class="vd-code-head">'
    r'<span class="vd-code-title">([^<]*)</span>'
)
LEAF_MARKER = re.compile(
    r'<span class="vd-file-tree-leaf" data-file="([^"]*)">([^<]*)</span>'
)

Entry = Mapping[str, object]


@dataclass
class Folder:
    name: str
    path: str
    folders: dict[str, Folder] = field(default_factory=dict)
    files: dict[str, Entry] = field(default_factory=dict)

    def count(self) -> int:
        return len(self.files) + sum(f.count() for f in self.folders.values())


def fold(entries: Sequence[Entry]) -> Folder:
    """Nest the flat `path` list. A path that appears twice is a fault (ValueError)."""
    root = Folder("", "")
    for entry in entries:
        *dirs, leaf = str(entry["path"]).split("/")
        folder = root
        for name in dirs:
            if name in folder.files:
                raise ValueError(f"'{folder.path}/{name}' is both a file and a folder")
            path = f"{folder.path}/{name}" if folder.path else name
            folder = folder.folders.setdefault(name, Folder(name, path))
        if leaf in folder.files or leaf in folder.folders:
            raise ValueError(f"path '{entry['path']}' appears more than once")
        folder.files[leaf] = entry
    return root


def _ordered(items: Mapping[str, object]) -> list[str]:
    return sorted(items, key=lambda name: (name.casefold(), name))


def compact(folder: Folder) -> Folder:
    """Follow a chain of folders that each hold only one folder; keep its name."""
    names = [folder.name]
    while len(folder.folders) == 1 and not folder.files:
        folder = next(iter(folder.folders.values()))
        names.append(folder.name)
    return Folder("/".join(names), folder.path, folder.folders, folder.files)


def summary_text(entries: Sequence[Entry]) -> str:
    """`5 files: 2 added, 1 modified, 2 unchanged`; the parts add up to the files."""
    changes = [change_of(e)[0] for e in entries]
    parts = [f"{changes.count(c)} {c}" for c in GLYPHS if c in changes]
    if "" in changes:
        parts.append(f"{changes.count('')} unchanged")
    noun = "file" if len(entries) == 1 else "files"
    return f"{len(entries)} {noun}: {', '.join(parts)}"


def _label(entry: Entry) -> str:
    change, was = change_of(entry)
    text = f"{change} " if change else ""
    text += str(entry["path"])
    text += f" (was {was})" if was else ""
    text += f" ({entry['role']})" if entry.get("role") else ""
    return text + (f": {entry['note']}" if entry.get("note") else "")


def _file(leaf: str, entry: Entry) -> str:
    change, was = change_of(entry)
    marker = f'<span class="vd-file-tree-leaf" data-file="{esc(entry["path"])}">'
    name = change_name(f"{marker}{esc(leaf)}</span>", change, was)
    badge = change_badge(change, "") + " " if change else ""
    role = entry.get("role")
    role_html = f' <span class="vd-file-tree-role">{esc(role)}</span>' if role else ""
    note = entry.get("note")
    note_html = f' <span class="vd-file-tree-note">{esc(note)}</span>' if note else ""
    row = f'<span class="vd-file-tree-row">{badge}{name}{role_html}{note_html}</span>'
    cls = "vd-file-tree-file"
    cls += f" vd-change-row vd-change-{change}" if change else ""
    label = esc(_label(entry))
    return f'<li class="{cls}" role="treeitem" aria-label="{label}">{row}</li>'


def _folder(folder: Folder, depth: int, collapse: int | None) -> str:
    shown = compact(folder)
    count = shown.count()
    noun = "file" if count == 1 else "files"
    is_open = collapse is None or depth <= collapse
    label = esc(f"folder {shown.path}, {count} {noun}")
    head = (
        f'<summary class="vd-file-tree-sum" aria-label="{label}">'
        f'<span class="vd-file-tree-dir">{esc(shown.name)}/</span> '
        f'<span class="vd-file-tree-count">{count} {noun}</span></summary>'
    )
    return (
        f'<li class="vd-file-tree-folder" role="treeitem">'
        f"<details{' open' if is_open else ''}>{head}"
        f"{_list(shown, depth + 1, collapse)}</details></li>"
    )


def _list(folder: Folder, depth: int, collapse: int | None, label: str = "") -> str:
    items = [
        _folder(folder.folders[n], depth, collapse) for n in _ordered(folder.folders)
    ]
    items += [_file(n, folder.files[n]) for n in _ordered(folder.files)]
    flat = " vd-file-tree-flat" if depth > MAX_INDENT_LEVEL else ""
    role = f'role="tree" aria-label="{esc(label)}"' if label else 'role="group"'
    return f'<ul class="vd-file-tree-list{flat}" {role}>{"".join(items)}</ul>'


def copy_text(folder: Folder, indent: int = 0) -> str:
    """An indented plain list: `name/` for folders, `<glyph> name` for changed files."""
    lines: list[str] = []
    pad = "  " * indent
    for name in _ordered(folder.folders):
        lines.append(f"{pad}{name}/")
        lines.append(copy_text(folder.folders[name], indent + 1))
    for name in _ordered(folder.files):
        change, was = change_of(folder.files[name])
        glyph = f"{GLYPHS[change]} " if change else ""
        lines.append(f"{pad}{glyph}{name}{f' (was {was})' if was else ''}")
    return "\n".join(line for line in lines if line)


def render_file_tree(data: dict[str, object]) -> str:
    entries = as_list(data["entries"])
    root = fold(entries)
    raw_collapse = data.get("collapse")
    collapse = raw_collapse if isinstance(raw_collapse, int) else None
    title = str(data.get("title", ""))
    heading = f'<p class="vd-file-tree-title">{esc(title)}</p>' if title else ""
    summary = summary_text(entries)
    copy = "\n".join(filter(None, [title, summary, copy_text(root)]))
    return (
        f'<div class="vb file-tree vd-file-tree"{copy_attr(copy)}>{heading}'
        f'<p class="vb-alt vd-file-tree-summary">{esc(summary)}</p>'
        f"{_list(root, 1, collapse, title or 'Changed files')}</div>"
    )


def code_titles(part_html: str) -> list[str]:
    """The titles of the `code` panels in one block's HTML, as authored."""
    return [html.unescape(t) for t in CODE_TITLE.findall(part_html)]


def match_target(path: str, titles: Mapping[str, str]) -> str:
    """The anchor of the code block whose title is the path or a trailing part of it."""
    if path in titles:
        return titles[path]
    tails = [t for t in titles if path.endswith("/" + t)]
    return titles[max(tails, key=len)] if tails else ""


def link_files(block_html: str, titles: Mapping[str, str]) -> str:
    """Turn each file leaf that has a matching code block into a plain `#id` link."""

    def swap(found: re.Match[str]) -> str:
        anchor = match_target(html.unescape(found.group(1)), titles)
        if not anchor:
            return found.group(0)
        return (
            f'<a class="vd-file-tree-link" href="#{esc(target_id(anchor))}">'
            f"{found.group(2)}</a>"
        )

    return LEAF_MARKER.sub(swap, block_html)


def target_id(anchor: str) -> str:
    """The DOM id a linked block gets."""
    return f"blk-{anchor}"
