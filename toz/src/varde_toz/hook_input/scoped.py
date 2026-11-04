"""Classify commands whose final pipeline stage bounds its output."""

BOUNDING_PROGRAMS = {"head", "tail", "grep", "rg", "wc", "cut", "awk"}


def _has_doubt(source: str) -> bool:
    quote = None
    i = 0
    size = len(source)
    while i < size:
        c = source[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if quote == '"' and (
                c == "`" or (c == "$" and i + 1 < size and source[i + 1] == "(")
            ):
                return True
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
        elif c == "\\":
            i += 2
            continue
        elif (
            (c == "$" and i + 1 < size and source[i + 1] == "(")
            or c == "`"
            or c in "<>"
        ):
            return True
        elif c == "&":
            if i + 1 < size and source[i + 1] == "&":
                i += 2
                continue
            return True
        i += 1
    return quote is not None


def _last_separator(text: str, separators: tuple[str, ...]) -> str | None:
    quote = None
    i = last = 0
    size = len(text)
    by_first = {}
    for separator in separators:
        by_first.setdefault(separator[0], []).append(separator)
    while i < size:
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        sep = next((s for s in by_first.get(c, ()) if text.startswith(s, i)), None)
        if sep:
            i += len(sep)
            last = i
        else:
            i += 1
    return None if quote else text[last:]


def _words(stage: str) -> list[str] | None:
    words, current = [], []
    quote = None
    in_word = False
    i = 0
    size = len(stage)
    while i < size:
        c = stage[i]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"':
                if i + 1 < size and stage[i + 1] in '"\\':
                    i += 1
                    current.append(stage[i])
                else:
                    current.append("\\")
            else:
                current.append(c)
        elif c in "'\"":
            quote, in_word = c, True
        elif c == "\\":
            i += 1
            if i >= len(stage):
                return None
            current.append(stage[i])
            in_word = True
        elif c.isspace():
            if in_word:
                words.append("".join(current))
                current = []
                in_word = False
        else:
            current.append(c)
            in_word = True
        i += 1
    if quote:
        return None
    if in_word:
        words.append("".join(current))
    return words


def is_scoped(source: str) -> bool:
    if _has_doubt(source):
        return False
    segment = _last_separator(source, (";", "\n", "&&", "||"))
    stage = _last_separator(segment, ("|",)) if segment is not None else None
    words = _words(stage) if stage is not None else None
    if not words:
        return False
    program, args = words[0].rsplit("/", 1)[-1], words[1:]
    if program in BOUNDING_PROGRAMS:
        return True
    if program == "sed":
        return "-n" in args
    if program != "git":
        return False
    subcommand = next(
        (i for i, arg in enumerate(args) if not arg.startswith("-")), None
    )
    if subcommand is None or args[subcommand] != "log":
        return False
    return any(
        arg in ("-n", "--max-count")
        or arg.startswith("--max-count=")
        or (len(arg) > 1 and arg[0] == "-" and arg[1:].isdigit())
        for arg in args[subcommand + 1 :]
    )
