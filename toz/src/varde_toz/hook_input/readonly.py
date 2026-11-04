"""Conservative shell read-only classifier used for per-tool thresholds."""


def _git_readonly(args: list[str]) -> bool:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-C", "-c", "--git-dir", "--work-tree"):
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return arg in ("show", "diff", "log", "status") and not any(
            x.startswith("--output") for x in args
        )
    return False


def _segment(words: list[str]) -> bool:
    while words and words[0] in ("do", "done"):
        words = words[1:]
    if not words:
        return True
    cmd, args = words[0], words[1:]
    if cmd == "for" or cmd in ("cd", "echo"):
        return True
    if cmd in ("while", "until"):
        return _segment(args)
    if cmd in ("cat", "head", "tail", "nl", "grep", "rg", "ls", "wc"):
        return True
    if cmd == "sed":
        return "-n" in args and not any(
            a.startswith(("-i", "--in-place")) or _sed_write(a) for a in args
        )
    if cmd == "find":
        return not any(
            a in ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fls")
            or a.startswith("-fprint")
            for a in args
        )
    return _git_readonly(args) if cmd == "git" else False


def _sed_write(script: str) -> bool:
    script = script.strip("'\"")
    if "/w " in script or script.endswith("/w"):
        return True
    for iter_clause in script.replace("\n", ";").split(";"):
        clause = iter_clause.lstrip("0123456789$ ,~+-")
        if clause.split()[:1] in (["w"], ["W"]):
            return True
    return False


def is_readonly(command: str) -> bool:
    command = command.replace("2>&1", "")
    if any(x in command for x in ("$(", "`", ">", "<")):
        return False
    command = command.replace("&&", "\n").replace("||", "\n")
    if "&" in command:
        return False
    return all(
        _segment(segment.split())
        for segment in command.replace(";", "\n").replace("|", "\n").splitlines()
    )
