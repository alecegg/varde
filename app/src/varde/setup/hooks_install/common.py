"""Small process and file helpers shared by hook installers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def home_dir() -> Path:
    value = os.environ.get("HOME")
    if not value:
        raise RuntimeError("HOME is not set")
    return Path(value)


def shell_quote(word: str) -> str:
    def plain(char: str) -> bool:
        return char.isascii() and (char.isalnum() or char in "/._-+:@")

    return (
        word
        if all(plain(char) for char in word)
        else "'" + word.replace("'", "'\\''") + "'"
    )


def shell_words(command: str) -> list[str]:
    """Split shell-style words with tolerance for incomplete quoting."""
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    started = False
    index = 0
    while index < len(command):
        char = command[index]
        index += 1
        if quote is None and char == "\\":
            if index < len(command):
                current.append(command[index])
                index += 1
                started = True
        elif (
            quote == '"'
            and char == "\\"
            and index < len(command)
            and command[index] in ('"', "\\")
        ):
            current.append(command[index])
            index += 1
        elif quote is not None and char == quote:
            quote = None
        elif quote is not None:
            current.append(char)
        elif char in ("'", '"'):
            quote = char
            started = True
        elif char.isspace():
            if started:
                words.append("".join(current))
                current.clear()
                started = False
        else:
            current.append(char)
            started = True
    if started:
        words.append("".join(current))
    return words


def write_atomic(path: Path, text: str) -> None:
    """Replace a target atomically from a temporary file in its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.resolve() if path.exists() else path
    mode = target.stat().st_mode if target.exists() else None
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{target.name}.varde-tmp-", dir=target.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        if mode is not None:
            temp.chmod(mode)
        os.replace(temp, target)
    except OSError as error:
        temp.unlink(missing_ok=True)
        raise OSError(f"writing {path}: {error}") from error
