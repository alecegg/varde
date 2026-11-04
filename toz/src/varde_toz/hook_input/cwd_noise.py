"""Remove Claude Code's shell cwd reset notice while preserving other text."""

NOISE_PREFIX = "Shell cwd was reset to "


def strip(text: str) -> str:
    if NOISE_PREFIX not in text:
        return text
    kept = []
    segments = text.split("\n")
    for index, content in enumerate(segments):
        terminator = "\n" if index + 1 < len(segments) else ""
        line = content[:-1] if terminator and content.endswith("\r") else content
        if not line.startswith(NOISE_PREFIX):
            kept.append(content + terminator)
    result = "".join(kept)
    return "" if not result.strip("\r\n") else result
