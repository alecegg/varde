"""Content sniffing, sectioning, and preview helpers ported from toz-core."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from .chunk import Chunk, fixed_window, truncate, truncate_middle
from .profile import Profile

MAX_BYTES = 3 * 1024
MAX_LINES = 120
MIN_BYTES = 300
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
MARKDOWN_SEGMENT_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
TEST_SECTION_PATTERNS = (
    re.compile(r"^---- (\S+) (stdout|stderr) ----$"),
    re.compile(r"^_{3,} (.+?) _{3,}$"),
    re.compile(r"^\s*● (.+)$"),
    re.compile(r"^\s*(PASS|FAIL) (\S+)"),
    re.compile(
        r"^={3,} .*(?:passed|failed|error|FAILURES|ERRORS|short test summary).* ={3,}$"
    ),
)
TEST_OUTPUT_LINE = re.compile(r"^test \S+ \.\.\. (?:ok|FAILED|ignored)")
TEST_FAILURE_LINE = re.compile(r"^---- \S+ (?:stdout|stderr) ----$")
TEST_SEPARATOR_LINE = re.compile(r"^_{3,} .+ _{3,}$")
TEST_SUMMARY_LINE = TEST_SECTION_PATTERNS[-1]
TEST_STATUS_LINE = re.compile(r"^\s*(?:PASS|FAIL) \S+")
TEST_DOT_LINE = re.compile(r"^\s*● .+")
CODE_DEFINITION_HINTS = (
    "pub",
    "async ",
    "unsafe ",
    "const ",
    "extern ",
    "fn ",
    "struct ",
    "enum ",
    "trait ",
    "impl ",
    "mod ",
    "type ",
    "macro_rules!",
    "def ",
    "class ",
    "export ",
    "function",
    "interface ",
    "let ",
    "var ",
    "func ",
    "public ",
    "private ",
    "protected ",
    "internal ",
    "static ",
    "final ",
    "abstract ",
    "override ",
    "virtual ",
    "synchronized ",
    "module ",
    "describe(",
    "context(",
    "it(",
    "test(",
)


class Strategy(StrEnum):
    DIFF = "Diff"
    JSON = "Json"
    MARKDOWN = "Markdown"
    TEST = "Test"
    LOG = "Log"
    CODE = "Code"
    FIXED = "Fixed"


@dataclass
class Segment:
    start: int
    end: int
    title: str


def _classify(lines: list[str]) -> str:
    nonblank = [line.rstrip() for line in lines if line.strip()]
    codeish = sum(
        (line.startswith(("  ", "\t")) and any(c in line for c in "{};()=[]="))
        or line.endswith(("{", "}", ";", ",", ")"))
        for line in nonblank
    )
    return "code" if nonblank and codeish * 10 > len(nonblank) * 4 else "prose"


def detect(text: str, *, lines: list[str] | None = None) -> Strategy:
    lines = text.splitlines() if lines is None else lines
    if len(lines) < 4:
        return Strategy.FIXED
    if _looks_diff(lines):
        return Strategy.DIFF
    if _looks_json(text, lines):
        return Strategy.JSON
    if _looks_code(lines):
        return Strategy.CODE
    if _looks_markdown(lines):
        return Strategy.MARKDOWN
    if _looks_test(lines):
        return Strategy.TEST
    if _looks_log(lines, text):
        return Strategy.LOG
    return Strategy.FIXED


def chunk_default_content(text: str, *, lines: list[str] | None = None) -> list[Chunk]:
    lines = text.splitlines() if lines is None else lines
    return _chunk_with_lines(detect(text, lines=lines), text, lines)


def chunk_with(strategy: Strategy, text: str) -> list[Chunk]:
    lines = text.splitlines()
    return _chunk_with_lines(strategy, text, lines)


def _chunk_with_lines(strategy: Strategy, text: str, lines: list[str]) -> list[Chunk]:
    if not lines:
        return []
    if strategy == Strategy.FIXED:
        return fixed_window(text, _lines=lines)
    byte_offsets = _byte_offsets(lines)
    return _finish(
        _segments(strategy, lines, byte_offsets), lines, text, True, byte_offsets
    )


def chunk_with_profile(
    text: str, profile: Profile, *, lines: list[str] | None = None
) -> list[Chunk]:
    lines = text.splitlines() if lines is None else lines
    if not lines:
        return []
    kind = profile.sections_kind
    strategy = None
    if kind not in ("heading", "start", "jsonl_key"):
        strategy = detect(text)
        if strategy == Strategy.FIXED:
            return fixed_window(text, _lines=lines)
    byte_offsets = _byte_offsets(lines)
    if kind == "heading":
        if profile.sections_pattern is None:
            raise AssertionError("heading strategy requires a section pattern")
        segments = [
            Segment(i, len(lines), (m.group(1) if m.lastindex else m.group(0)))
            for i, line in enumerate(lines)
            if (m := profile.sections_pattern.search(line))
        ]
    elif kind == "start":
        if profile.sections_pattern is None:
            raise AssertionError("start strategy requires a section pattern")
        segments = [
            Segment(i, len(lines), m.group(0))
            for i, line in enumerate(lines)
            if (m := profile.sections_pattern.search(line))
        ]
    elif kind == "jsonl_key":
        segments = _jsonl_segments(profile.jsonl_key or "", lines)
    else:
        if strategy is None:
            raise AssertionError("non-section strategy must be detected")
        segments = _segments(strategy, lines, byte_offsets)
    return _finish(segments, lines, text, profile.merge_small, byte_offsets)


def _segments(
    strategy: Strategy, lines: list[str], byte_offsets: list[int]
) -> list[Segment]:
    if strategy == Strategy.JSON:
        return _json_segments(lines, byte_offsets)
    return {
        Strategy.DIFF: _diff_segments,
        Strategy.MARKDOWN: _markdown_segments,
        Strategy.TEST: _test_segments,
        Strategy.LOG: _log_segments,
        Strategy.CODE: _code_segments,
    }[strategy](lines)


def _finish(
    segments: list[Segment],
    lines: list[str],
    text: str,
    merge_small: bool,
    byte_offsets: list[int],
) -> list[Chunk]:
    segments = _split_large(
        _merge_small(_cover(segments, lines), byte_offsets, merge_small),
        lines,
        byte_offsets,
    )
    if not segments:
        return fixed_window(text, _lines=lines)
    return [
        Chunk(
            i,
            truncate_middle(s.title, 100),
            s.start + 1,
            s.end,
            _classify(lines[s.start : s.end]),
            "\n".join(lines[s.start : s.end]),
        )
        for i, s in enumerate(segments)
    ]


def _cover(segments: list[Segment], lines: list[str]) -> list[Segment]:
    n = len(lines)
    segments = sorted(
        (s for s in segments if s.end > s.start and s.start < n), key=lambda s: s.start
    )
    out = []
    cursor = 0
    for i, segment in enumerate(segments):
        start = 0 if i == 0 else max(segment.start, cursor)
        end = min(max(segments[i + 1].start, start), n) if i + 1 < len(segments) else n
        if end > start:
            out.append(Segment(start, end, segment.title))
            cursor = end
    if not out and n:
        out.append(Segment(0, n, _title(lines)))
    if out:
        out[-1].end = n
    return out


def _byte_offsets(lines: list[str]) -> list[int]:
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode()) + 1)
    return offsets


def _bytes(offsets: list[int], segment: Segment) -> int:
    return offsets[segment.end] - offsets[segment.start]


def _merge_small(
    segments: list[Segment], byte_offsets: list[int], enabled: bool
) -> list[Segment]:
    out: list[Segment] = []
    for segment in segments:
        if out and enabled and _bytes(byte_offsets, out[-1]) < MIN_BYTES:
            previous = out[-1]
            if _bytes(byte_offsets, segment) > _bytes(byte_offsets, previous):
                previous.title = segment.title
            previous.end = segment.end
        else:
            out.append(segment)
    return out


def _split_large(
    segments: list[Segment], lines: list[str], byte_offsets: list[int]
) -> list[Segment]:
    result = []
    for segment in segments:
        if (
            _bytes(byte_offsets, segment) <= MAX_BYTES
            and segment.end - segment.start <= MAX_LINES
        ):
            result.append(segment)
            continue
        parts = []
        start = segment.start
        byte_count = 0
        i = start
        while i < segment.end:
            line_bytes = byte_offsets[i + 1] - byte_offsets[i]
            if i > start and (
                byte_count + line_bytes > MAX_BYTES or i - start >= MAX_LINES
            ):
                cuts = [
                    k
                    for k in range(start + 1, i + 1)
                    if not lines[k - 1].strip() and k - start >= MAX_LINES // 4
                ]
                cut = cuts[-1] if cuts else i
                parts.append((start, cut))
                start = cut
                byte_count = byte_offsets[i] - byte_offsets[start]
            byte_count += line_bytes
            i += 1
        if start < segment.end:
            parts.append((start, segment.end))
        for index, (part_start, part_end) in enumerate(parts, 1):
            title = (
                f"{segment.title} ({index}/{len(parts)})"
                if len(parts) > 1
                else segment.title
            )
            result.append(Segment(part_start, part_end, title))
    return result


def _title(lines: list[str]) -> str:
    return truncate(next((line.strip() for line in lines if line.strip()), ""), 72)


def _looks_diff(lines: list[str]) -> bool:
    head = lines[:200]
    return any(line.startswith("diff --git ") for line in head) or (
        any(line.startswith("--- ") for line in head)
        and any(line.startswith("+++ ") for line in head)
        and any(line.startswith("@@ ") for line in head)
    )


def _diff_segments(lines: list[str]) -> list[Segment]:
    git = any(line.startswith("diff --git ") for line in lines)
    segments: list[Segment] = []
    filename = ""
    for i, line in enumerate(lines):
        match = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if match:
            _close(segments, i)
            filename = match.group(2)
            segments.append(Segment(i, i, filename))
            continue
        if (
            not git
            and line.startswith("--- ")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("+++ ")
        ):
            plus = re.match(r"^\+\+\+ (?:b/)?(\S+)", lines[i + 1])
            filename = plus.group(1) if plus else ""
            _close(segments, i)
            segments.append(Segment(i, i, filename))
            continue
        match = re.match(r"^@@ .*?@@ ?(.*)$", line)
        if match:
            context = match.group(1).strip()
            _close(segments, i)
            segments.append(
                Segment(i, i, f"{filename} — {context}" if context else filename)
            )
    _close(segments, len(lines))
    return segments


def _close(segments: list[Segment], at: int) -> None:
    if segments and segments[-1].end < at:
        segments[-1].end = at


def _looks_json(text: str, lines: list[str]) -> bool:
    trimmed = text.lstrip()
    if not trimmed.startswith(("{", "[")):
        return False
    endings = (",", "{", "[", "}", "]", '"', "null", "true", "false")
    nonblank = [line for line in lines if line.strip()]
    jsonish = sum(
        line.rstrip().endswith(endings) or line.rstrip()[-1:].isdigit()
        for line in nonblank
    )
    try:
        json.loads(text)
        return bool(nonblank) and jsonish * 10 >= len(nonblank) * 9
    except ValueError:
        return False


def _json_segments(lines: list[str], byte_offsets: list[int]) -> list[Segment]:
    info = _json_lines(lines)
    segments: list[Segment] = []
    _json_split(lines, info, byte_offsets, 0, len(lines), 1, segments)
    return segments


@dataclass
class JsonLine:
    path: str | None
    depth: int


def _json_lines(lines: list[str]) -> list[JsonLine]:
    stack: list[tuple[bool, int]] = []
    labels: list[str] = []
    output = []
    for line in lines:
        value = line.strip()
        if not value:
            output.append(JsonLine(None, len(stack)))
            continue
        if value.startswith(("}", "]")):
            if stack:
                stack.pop()
            del labels[max(0, len(stack) - 1) :]
            output.append(JsonLine(None, len(stack)))
            continue
        depth = len(stack)
        path = None
        if stack:
            is_array, count = stack[-1]
            label = f"[{count}]" if is_array else (_json_key(value) or f"[{count}]")
            stack[-1] = (is_array, count + 1)
            del labels[max(0, depth - 1) :]
            labels.append(label)
            path = _join_path(labels)
        opener = value.rstrip(",")
        if opener.endswith("{"):
            stack.append((False, 0))
        elif opener.endswith("["):
            stack.append((True, 0))
        output.append(JsonLine(path, depth))
    return output


def _json_key(line: str) -> str | None:
    match = re.match(r'^"(.*?)":', line)
    return match.group(1) if match else None


def _join_path(labels: list[str]) -> str:
    value = ""
    for label in labels:
        if label.startswith("["):
            value += label
        else:
            value += ("." if value else "") + label
    return value


def _json_split(
    lines: list[str],
    info: list[JsonLine],
    byte_offsets: list[int],
    start: int,
    end: int,
    depth: int,
    output: list[Segment],
) -> None:
    starts = [
        i
        for i in range(start, end)
        if info[i].depth == depth and info[i].path is not None
    ]
    if not starts or depth > 6:
        title = next(
            (item.path for item in info[start:end] if item.path),
            _title(lines[start:end]),
        )
        output.append(Segment(start, end, title))
        return
    pending: Segment | None = None
    last_label = ""
    for k, index in enumerate(starts):
        segment_start = start if k == 0 else index
        segment_end = starts[k + 1] if k + 1 < len(starts) else end
        label = info[index].path or ""
        segment = Segment(segment_start, segment_end, label)
        size = _bytes(byte_offsets, segment)
        has_children = any(
            info[i].depth == depth + 1 and info[i].path is not None
            for i in range(segment_start, segment_end)
        )
        if size > MAX_BYTES and has_children:
            if pending:
                output.append(_json_range(pending, last_label))
                pending = None
            _json_split(
                lines, info, byte_offsets, segment_start, segment_end, depth + 1, output
            )
            continue
        if pending and _bytes(byte_offsets, pending) + size <= MAX_BYTES:
            pending.end = segment.end
            last_label = label
        else:
            if pending:
                output.append(_json_range(pending, last_label))
            pending, last_label = segment, label
    if pending:
        output.append(_json_range(pending, last_label))


def _json_range(segment: Segment, last: str) -> Segment:
    if segment.title != last:
        segment.title = _range_title(segment.title, last)
    return segment


def _range_title(first: str, last: str) -> str:
    i, j = first.rfind("["), last.rfind("[")
    if i >= 0 and j >= 0 and first[:i] == last[:j]:
        a, b = first[i + 1 :], last[j + 1 :]
        if (
            a.endswith("]")
            and b.endswith("]")
            and a[:-1].isdigit()
            and b[:-1].isdigit()
        ):
            return f"{first[:i]}[{a[:-1]}..{b[:-1]}]"
    tail = re.split(r"[.\[]", last)[-1]
    return f"{first} … {tail}"


def _jsonl_segments(key: str, lines: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    current = object()
    for i, line in enumerate(lines):
        try:
            value = json.loads(line.strip())
            for part in key.split("."):
                value = value[part]
            title = (
                value
                if isinstance(value, str)
                else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            )
        except ValueError, TypeError, KeyError, IndexError:
            title = None
        if title != current:
            segments.append(Segment(i, len(lines), title or ""))
            current = title
    return segments


def _looks_markdown(lines: list[str]) -> bool:
    headings = 0
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#") and MARKDOWN_HEADING.match(line):
            headings += 1
    return headings >= 2


def _markdown_segments(lines: list[str]) -> list[Segment]:
    segments = []
    breadcrumbs: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = (
            MARKDOWN_SEGMENT_HEADING.match(line)
            if line.startswith(("#", " ", "\t"))
            else None
        )
        if heading:
            depth, title = len(heading.group(1)), heading.group(2).strip()
            breadcrumbs = [
                (level, value) for level, value in breadcrumbs if level < depth
            ]
            breadcrumbs.append((depth, title))
            if segments:
                segments[-1].end = i
            segments.append(
                Segment(i, len(lines), " > ".join(value for _, value in breadcrumbs))
            )
    if segments and segments[0].start > 0:
        segments.insert(
            0, Segment(0, segments[0].start, _title(lines[: segments[0].start]))
        )
    return segments


def _test_section_title(line: str) -> str | None:
    if line.startswith("---- "):
        match = TEST_SECTION_PATTERNS[0].match(line)
        if match:
            return f"FAIL {match.group(1)}"
    if line.startswith("___"):
        match = TEST_SECTION_PATTERNS[1].match(line)
        if match:
            return f"FAIL {match.group(1)}"
    stripped = line.lstrip()
    if stripped.startswith("● "):
        match = TEST_SECTION_PATTERNS[2].match(line)
        if match:
            return f"● {match.group(1).strip()}"
    if stripped.startswith(("PASS ", "FAIL ")):
        match = TEST_SECTION_PATTERNS[3].match(line)
        if match:
            return f"{match.group(1)} {match.group(2)}"
    if (
        line.startswith("running ")
        and line.endswith(" tests")
        or line.startswith(("running 1 test", "failures:", "test result:"))
    ):
        return line
    if line.startswith("===") and TEST_SUMMARY_LINE.match(line):
        return line.strip("= ")
    return None


def _looks_test(lines: list[str]) -> bool:
    score = 0
    for line in lines:
        if (
            line.startswith("test ")
            and TEST_OUTPUT_LINE.match(line)
            or line.startswith("---- ")
            and TEST_FAILURE_LINE.match(line)
        ):
            score += 1
        elif (
            line.startswith("___")
            and TEST_SEPARATOR_LINE.match(line)
            or line.startswith("===")
            and TEST_SUMMARY_LINE.match(line)
        ):
            score += 2
        elif (
            line.lstrip().startswith(("PASS ", "FAIL "))
            and TEST_STATUS_LINE.match(line)
            or line.lstrip().startswith("● ")
            and TEST_DOT_LINE.match(line)
        ):
            score += 1
        if score >= 3:
            return True
    return False


def _test_segments(lines: list[str]) -> list[Segment]:
    segments = []
    for i, line in enumerate(lines):
        title = _test_section_title(line)
        if title:
            if segments:
                segments[-1].end = i
            segments.append(Segment(i, len(lines), title))
    return segments


LOG_PREFIX = re.compile(
    r"(?ix)^\s*(\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}|\[?\d{2}:\d{2}:\d{2}|\[?\d{10,13}\]?\s|\[?(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|PANIC|CRITICAL)\]?[:\s]|(error|warning)(\[E\d+\])?:)"
)
LOG_MARKER = re.compile(
    r"(?i)^.{0,48}?\b(error|warn|warning|fatal|panic|panicked|failed|exception|traceback|critical)\b"
)
LOG_PREFIX_LINES = re.compile(
    r"(?im)^[ \t]*(?:\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|\[?\d{2}:\d{2}:\d{2}|"
    r"\[?\d{10,13}\]?[ \t]|"
    r"\[?(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|PANIC|CRITICAL)\]?[: \t]|"
    r"(?:error|warning)(?:\[E\d+\])?:)"
)
LOG_MARKER_LINES = re.compile(
    r"(?im)^.{0,48}?\b(?:error|warn|warning|fatal|panic|panicked|failed|exception|traceback|critical)\b"
)


def _looks_log(lines: list[str], text: str) -> bool:
    nonblank_count = sum(bool(line.strip()) for line in lines)
    if not nonblank_count:
        return False
    prefix_count = sum(1 for _ in LOG_PREFIX_LINES.finditer(text))
    if prefix_count * 10 >= nonblank_count * 3:
        return True
    return sum(1 for _ in LOG_MARKER_LINES.finditer(text)) >= 3


def _log_title(line: str) -> str:
    title = line.strip()
    for _ in range(2):
        match = LOG_PREFIX.search(title)
        if not match:
            break
        title = title[match.end() :].lstrip()
    if ": " in title:
        head, rest = title.split(": ", 1)
        if len(head) < 40 and (head.endswith("]") or " " not in head):
            title = rest.lstrip()
    return title or line.strip()


def _log_segments(lines: list[str]) -> list[Segment]:
    segments = []
    run_start = 0
    previous = False
    for i, line in enumerate(lines):
        marker = bool(LOG_MARKER.search(line))
        if i and ((marker and not previous) or i - run_start >= 80):
            _close(segments, i)
            segments.append(Segment(i, i, _log_title(line)))
            run_start = i
        elif not segments:
            segments.append(Segment(0, 0, _log_title(line)))
        previous = marker
    _close(segments, len(lines))
    return segments


DEFINITION = re.compile(
    r"^(?: {0,4}(?:(?:pub(?:\([^)]*\))?\s+)?"
    r"(?:async\s+|unsafe\s+|const\s+|extern\s+\S+\s+)*"
    r"(?:fn|struct|enum|trait|impl|mod|type|macro_rules!)\s+\S|"
    r"(?:async\s+)?def\s+\w+|class\s+\w+|"
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+\w+|class\s+\w+|interface\s+\w+|enum\s+\w+|type\s+\w+\s*=|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)|"
    r"func\s+(?:\([^)]*\)\s*)?\w+\s*\(|"
    r"(?:(?:public|private|protected|internal|static|final|abstract|override|virtual|synchronized)\s+)*(?:class|interface|enum|record|struct)\s+\w+|"
    r"(?:(?:public|private|protected|internal|static|final|abstract|override|virtual|synchronized)\s+)+[\w<>\[\],]+\s+\w+\s*\([^;]*$|"
    r"(?:module|describe|context|it|test)\s*\(|(?:def|module|class)\s+[A-Z]\w*))"
)


def _looks_code(lines: list[str]) -> bool:
    if _classify(lines) != "code":
        return False
    matches = 0
    for line in lines:
        candidate = line.lstrip().lower()
        if candidate.startswith(CODE_DEFINITION_HINTS):
            matches += bool(DEFINITION.search(line))
            if matches >= 3:
                return True
    return False


def _signature(line: str) -> str:
    value = line.strip().rstrip("{ ").strip()
    value = value.removesuffix("=>").rstrip(":= ").strip()
    value = re.sub(r"^export (?:default )?", "", value)
    return re.sub(r"^pub(?:\([^)]*\))?\s+", "", value)


def _code_segments(lines: list[str]) -> list[Segment]:
    segments = []
    for i, line in enumerate(lines):
        if DEFINITION.search(line):
            start = i
            while start > 0:
                previous = lines[start - 1].strip()
                attached = previous.startswith(
                    ("///", "//!", "#[", "@", "/**", "*", '"""')
                ) or (previous.startswith("#") and not previous.startswith("#!"))
                if not attached:
                    break
                start -= 1
            if segments and start <= segments[-1].start:
                continue
            if segments:
                segments[-1].end = start
            segments.append(Segment(start, len(lines), _signature(line)))
    if segments and segments[0].start > 0:
        segments.insert(
            0, Segment(0, segments[0].start, _title(lines[: segments[0].start]))
        )
    return segments


def preview_toc(
    chunks: list[Chunk], lines: list[str], profile: Profile, handle: str
) -> list[dict]:
    rows = []
    for chunk in chunks:
        section = lines[chunk.line_start - 1 : chunk.line_end]
        matching = [
            line
            for line in section
            if profile.item is None or profile.item.search(line)
        ]
        limit = (
            profile.items_per_section
            if profile.items_per_section is not None
            else len(matching)
        )
        rows.append(
            {
                "title": chunk.title,
                "items": len(matching),
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "lines": [truncate(line, 240) for line in matching[:limit]],
            }
        )
    return rows
