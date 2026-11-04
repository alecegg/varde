"""Translate `varde learn check|how|measure|docs` to the docs handler argv."""

from __future__ import annotations

from pathlib import Path

PAGE_VERBS = {
    "serve",
    "watch",
    "comments",
    "reply",
    "blocks",
    "recap",
    "build",
}
FREE_KINDS = {"flow", "ledger", "baseline"}
LEDGER_ACTIONS = ("validate", "check", "score")


class CommandError(ValueError):
    """The grouped command path is not valid."""


def _is_markdown_file(path: str) -> bool:
    name = Path(path).name
    return name.lower().endswith(".md") and name != "SKILL.md"


def _skill_dir(path: str) -> str:
    return str(Path(path).parent) if Path(path).name == "SKILL.md" else path


def check_runs(args: list[str]) -> list[list[str]]:
    """Map `check <path>... [--json] [--write]` to the handler argv list to run."""
    flags = [arg for arg in args if arg in {"--json", "--write"}]
    paths = [arg for arg in args if arg not in {"--json", "--write"}]
    json_flag = [arg for arg in flags if arg == "--json"]
    flow_flag = "--write" if "--write" in flags else "--check"
    if not paths:
        raise CommandError("usage: varde learn check [--json] [--write] <PATH>...")
    runs: list[list[str]] = []
    skills = [path for path in paths if not _is_markdown_file(path)]
    documents = [path for path in paths if _is_markdown_file(path)]
    if skills:
        runs.append(["lint", *json_flag, *skills])
        runs.append(["frontmatter", *json_flag, *skills])
        runs.append(["flow", flow_flag, *map(_skill_dir, skills)])
    if documents:
        runs.append(["lint", *json_flag, *documents])
        runs.extend(["blocks", "--check", document] for document in documents)
    return runs


def how_argv(args: list[str]) -> list[str]:
    """Map `how <skill> [step]` to the handler argv."""
    return ["how", *args]


def docs_argv(args: list[str]) -> list[str]:
    """Map `docs <verb> ...` to the handler argv."""
    if not args:
        raise CommandError(
            "usage: varde learn docs "
            "<serve|watch|comments|reply|blocks|recap|build|spec>"
        )
    verb, rest = args[0], args[1:]
    if verb == "spec":
        return ["spec", "inventory", *rest]
    if verb == "blocks" and "--check" in rest:
        raise CommandError(
            "use `varde learn check <doc.md>` to check a document's blocks"
        )
    if verb in PAGE_VERBS:
        return [verb, *rest]
    raise CommandError(f"unexpected command `docs {verb}`")


def _split_options(
    args: list[str], values: set[str]
) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    rest: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in values and index + 1 < len(args):
            options[token] = args[index + 1]
            index += 2
            continue
        rest.append(token)
        index += 1
    return options, rest


def ledger_runs(skill: str, args: list[str]) -> list[list[str]]:
    """Map `measure <skill> ledger [--ledger F] [--write] ...` to handler argv."""
    options, rest = _split_options(args, {"--ledger", "--route"})
    path = Path(skill)
    ledger = options.get("--ledger") or (
        skill if path.is_file() else str(path / "ledger.json")
    )
    shared = [arg for arg in rest if arg != "--write"]
    if "--write" in rest:
        return [["flow", "ledger", "hash", ledger, *shared]]
    route = ["--route", options["--route"]] if "--route" in options else []
    return [
        [
            "flow",
            "ledger",
            action,
            ledger,
            *shared,
            *(route if action == "score" else []),
        ]
        for action in LEDGER_ACTIONS
    ]


def measure_runs(skill: str, kind: str, args: list[str]) -> list[list[str]]:
    """Map `measure <skill> flow|ledger|baseline ...` to handler argv list."""
    if kind == "flow":
        return [["flow", *args, skill]]
    if kind == "ledger":
        return ledger_runs(skill, args)
    if kind == "baseline":
        return [["baseline", "status", *args, skill]]
    raise CommandError(f"unexpected measure kind `{kind}`")
