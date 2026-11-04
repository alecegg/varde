"""Build bounded command headings for shell output previews."""

from varde_toz.chunk import truncate


def _split(source: str) -> list[str]:
    commands, current, stack = [], [], []
    i = 0
    while i < len(source):
        c = source[i]
        context = stack[-1] if stack else None
        if context == "single":
            current.append(c)
            if c == "'":
                stack.pop()
        elif context == "double":
            current.append(c)
            if c == '"':
                stack.pop()
            elif c == "\\" and i + 1 < len(source):
                i += 1
                current.append(source[i])
            elif c == "$" and source[i + 1 : i + 2] == "(":
                i += 1
                current.append(source[i])
                stack.append("paren")
            elif c == "`":
                stack.append("backtick")
        elif context == "backtick":
            current.append(c)
            if c == "`":
                stack.pop()
            elif c == "\\" and i + 1 < len(source):
                i += 1
                current.append(source[i])
        elif context == "paren":
            current.append(c)
            if c == "'":
                stack.append("single")
            elif c == '"':
                stack.append("double")
            elif c == "`":
                stack.append("backtick")
            elif c == "(":
                stack.append("paren")
            elif c == ")":
                stack.pop()
            elif c == "$" and source[i + 1 : i + 2] == "(":
                i += 1
                current.append(source[i])
                stack.append("paren")
            elif c == "\\" and i + 1 < len(source):
                i += 1
                current.append(source[i])
        elif c in "'\"`(":
            current.append(c)
            stack.append(
                {"'": "single", '"': "double", "`": "backtick", "(": "paren"}[c]
            )
        elif c == "$" and source[i + 1 : i + 2] == "(":
            current.extend((c, "("))
            i += 1
            stack.append("paren")
        elif c == "\\" and i + 1 < len(source):
            i += 1
            current.extend(("\\", source[i]))
        elif (
            c == "&"
            and source[i + 1 : i + 2] == "&"
            or c == "|"
            and source[i + 1 : i + 2] == "|"
        ):
            i += 1
            _push(commands, current)
        elif c in ";\n":
            _push(commands, current)
        else:
            current.append(c)
        i += 1
    _push(commands, current)
    return commands


def _push(commands: list[str], current: list[str]) -> None:
    value = "".join(current).strip().replace("\n", " ").replace("\r", " ")
    if value:
        commands.append(value)
    current.clear()


def heading(source: str) -> str | None:
    commands = _split(source)
    if len(commands) < 2:
        return None
    parts = [
        f"{i}) {truncate(command, 60)}" for i, command in enumerate(commands[:5], 1)
    ]
    if len(commands) > 5:
        parts.append(f"+{len(commands) - 5} more")
    return "commands: " + " ".join(parts)
