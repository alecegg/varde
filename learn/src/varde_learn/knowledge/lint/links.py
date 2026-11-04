"""Markdown link extraction that ignores code and image links."""

LINK_MARKER = "]("


def extract_links(body: str) -> list[str]:
    return [target for _, _, target in link_spans(body)]


def link_spans(body: str) -> list[tuple[int, int, str]]:
    """Each local link as (start, end, target); body[start:end] is the target text."""
    mask = _code_mask(body)
    links: list[tuple[int, int, str]] = []
    index = 0
    while (start := body.find(LINK_MARKER, index)) >= 0:
        if mask[start] or _is_image_link(body, start):
            index = start + len(LINK_MARKER)
            continue
        target_start = start + len(LINK_MARKER)
        rest = body[target_start:]
        end = rest.find(")")
        if end < 0:
            end = len(rest)
        target = rest[:end]
        space = target.find(" ")
        if space >= 0 and target[space:].lstrip().startswith('"'):
            target = target[:space]
        target = target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        target = target.split("#", 1)[0].strip()
        if target and not target.startswith(("http://", "https://", "#")):
            offset = target_start + rest[:end].find(target)
            links.append((offset, offset + len(target), target))
        index = target_start + end
    return links


def _is_image_link(body: str, marker_start: int) -> bool:
    depth = 0
    for index in range(marker_start - 1, -1, -1):
        char = body[index]
        if char == "]":
            depth += 1
        elif char == "[":
            if depth == 0:
                return index > 0 and body[index - 1] == "!"
            depth -= 1
    return False


def _code_mask(body: str) -> list[bool]:
    mask = [False] * len(body)
    fence_marker: str | None = None
    fence_length = 0
    line_start = 0
    for line in body.splitlines(keepends=True):
        content = line.removesuffix("\n")
        trimmed = content.lstrip()
        marker = trimmed[:1]
        if fence_marker is not None:
            if marker == fence_marker:
                run_length = _marker_run(trimmed, fence_marker)
                if run_length >= fence_length and not trimmed[run_length:].strip():
                    fence_marker = None
            mask[line_start : line_start + len(line)] = [True] * len(line)
        elif marker in ("`", "~") and _marker_run(trimmed, marker) >= 3:
            fence_marker = marker
            fence_length = _marker_run(trimmed, marker)
            mask[line_start : line_start + len(line)] = [True] * len(line)
        else:
            _mask_inline_code(line, mask, line_start)
        line_start += len(line)
    return mask


def _marker_run(value: str, marker: str) -> int:
    return len(value) - len(value.lstrip(marker))


def _mask_inline_code(line: str, mask: list[bool], offset: int) -> None:
    open_length: int | None = None
    index = 0
    while index < len(line):
        if line[index] != "`":
            if open_length is not None:
                mask[offset + index] = True
            index += 1
            continue
        end = index
        while end < len(line) and line[end] == "`":
            end += 1
        run = end - index
        if open_length is None:
            open_length = run
        elif open_length == run:
            open_length = None
        for position in range(index, end):
            mask[offset + position] = True
        index = end
