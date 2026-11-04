"""CLI routing and help snapshots for ``learn docs|check|how|measure``."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from difflib import get_close_matches
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Never, cast

from varde_core.envelope import negative_result, success, tool_error


def _raise(error: Exception) -> Never:
    raise error


_HELP = {
    "": "docs.txt",
    "doc": "docs.txt",
    "docs": "docs.txt",
    "check": "check.txt",
    "how": "how.txt",
    "measure flow": "flow.txt",
    "measure ledger": "flow/ledger.txt",
    "measure baseline": "baseline.txt",
    "docs serve": "serve.txt",
    "docs watch": "watch.txt",
    "docs comments": "comments.txt",
    "docs reply": "reply.txt",
    "docs blocks": "blocks.txt",
    "docs recap": "recap.txt",
    "docs build": "build.txt",
    "docs spec": "spec/inventory.txt",
    "doc lint": "check.txt",
    "doc frontmatter": "check.txt",
    "doc how": "how.txt",
    "doc baseline": "baseline.txt",
    "doc baseline status": "baseline.txt",
    "doc flow": "flow.txt",
    "doc flow ledger": "flow/ledger.txt",
    "doc serve": "serve.txt",
    "doc watch": "watch.txt",
    "doc comments": "comments.txt",
    "doc reply": "reply.txt",
    "doc blocks": "blocks.txt",
    "doc recap": "recap.txt",
    "doc build": "build.txt",
    "doc spec inventory": "spec/inventory.txt",
}


def help_text(path: str = "") -> str:
    command = " ".join(path.split())
    command = command.removeprefix("varde ")
    if command in _HELP:
        return (
            files("varde_learn.docs")
            .joinpath("help", _HELP[command])
            .read_text(encoding="utf-8")
        )
    if command.startswith("doc flow ledger "):
        return (
            files("varde_learn.docs")
            .joinpath("help", "flow/ledger.txt")
            .read_text(encoding="utf-8")
        )
    return help_text(command.rsplit(" ", 1)[0])


class LedgerAction(str, Enum):
    HASH = "hash"
    VALIDATE = "validate"
    SCORE = "score"
    CHECK = "check"


@dataclass(frozen=True)
class SpecInventoryArgs:
    repository: Path
    knowledge: Path
    working: Path
    refresh: bool = False
    acknowledge_architecture_paths: tuple[Path, ...] = ()
    json: bool = False


class _UsageError(ValueError):
    pass


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _take_options(
    args: list[str], flags: set[str], values: set[str]
) -> tuple[dict[str, object], list[str]]:
    options: dict[str, object] = {}
    positional: list[str] = []
    index = 0
    positional_only = False
    while index < len(args):
        token = args[index]
        if token == "--" and not positional_only:  # noqa: S105 - This is a command-line option marker, not a credential.
            positional_only = True
            index += 1
            continue
        if not positional_only and token in {"-h", "--help"}:
            raise SystemExit(0)
        if not positional_only and token.startswith("--"):
            option, equals, inline_value = token.partition("=")
            key = option[2:].replace("-", "_")
            if key in flags:
                if equals:
                    raise _UsageError(
                        f"unexpected value '{inline_value}' for '{option}' found; "
                        "no more were expected"
                    )
                if key in options:
                    raise _UsageError(
                        f"the argument '{option}' cannot be used multiple times"
                    )
                options[key] = True
            elif key in values:
                if key != "acknowledge_architecture_path" and key in options:
                    placeholder = {
                        "root": "DIR",
                        "route": "NAME",
                        "repository": "REPOSITORY",
                        "knowledge": "KNOWLEDGE",
                        "working": "WORKING",
                    }.get(key, key.upper())
                    raise _UsageError(
                        f"the argument '{option} <{placeholder}>' cannot be used "
                        "multiple times"
                    )
                if equals:
                    value = inline_value
                    if not value:
                        raise _UsageError(f"a value is required for '{option}'")
                else:
                    index += 1
                    if index >= len(args) or args[index].startswith("--"):
                        raise _UsageError(f"a value is required for '{option}'")
                    value = args[index]
                if key == "acknowledge_architecture_path":
                    cast(
                        "list[Path]",
                        options.setdefault("acknowledge_architecture_paths", []),
                    ).append(Path(value))
                else:
                    options[key] = value
            else:
                candidates = {f"--{name.replace('_', '-')}" for name in flags | values}
                suggestion = get_close_matches(
                    option, sorted(candidates), n=1, cutoff=0.7
                )
                suffix = (
                    f"\n\n  tip: a similar argument exists: '{suggestion[0]}'"
                    if suggestion
                    else ""
                )
                raise _UsageError(f"unexpected argument '{option}'{suffix}")
        elif not positional_only and token.startswith("-"):
            raise _UsageError(f"unexpected argument '{token}'")
        else:
            positional.append(token)
        index += 1
    return options, positional


def _usage_error(
    args: list[str], command: str, message: str, *, json_error: bool = False
) -> int:
    code = {
        "lint": "doc_lint_usage",
        "frontmatter": "doc_frontmatter_usage",
        "flow": "doc_flow_usage",
        "how": "doc_how_usage",
        "baseline": "doc_baseline_usage",
        "comments": "doc_pages_usage",
        "reply": "doc_pages_usage",
    }.get(command)
    ledger = command == "flow" and args and args[0] == "ledger"
    inventory = command == "spec" and args and args[0] == "inventory"
    help_command = (
        "doc flow ledger"
        if ledger
        else "doc spec inventory"
        if inventory
        else f"doc {command}"
    )
    text = help_text(help_command)
    usage = next((line for line in text.splitlines() if line.startswith("Usage: ")), "")
    if ledger:
        usage = (
            "Usage: varde learn measure <SKILL> ledger [OPTIONS] <ACTION> <LEDGER>"
            if any(arg.startswith("--") for arg in args)
            else "Usage: varde learn measure <SKILL> ledger <ACTION> <LEDGER>"
        )
    elif inventory:
        usage = (
            "Usage: varde learn docs spec --repository <REPOSITORY> "
            "--knowledge <KNOWLEDGE> --working <WORKING>"
        )
    elif command in {"lint", "frontmatter"} and "required arguments" in message:
        usage = "Usage: varde learn check <PATH>..."
    elif command == "flow":
        if "required arguments" in message:
            usage = "Usage: varde learn measure <SKILL> flow"
        else:
            usage = "Usage: varde learn measure <SKILL> flow [OPTIONS]"
    if "required arguments were not provided" in message:
        required = message.removeprefix(
            "the following required arguments were not provided: "
        )
        detail = (
            "error: the following required arguments were not provided:\n"
            + "\n".join(f"  {item}" for item in required.split(", "))
        )
    elif message.startswith("unexpected argument '"):
        body = message.removeprefix("unexpected argument '")
        argument, _, tip = body.partition("'\n\n  tip:")
        if not tip:
            argument = body.removesuffix("'")
        detail = f"error: unexpected argument '{argument}' found"
        if tip:
            detail += f"\n\n  tip:{tip}"
        else:
            detail += f"\n\n  tip: to pass '{argument}' as a value, use '-- {argument}'"
    elif message.startswith("unexpected value '"):
        detail = f"error: {message}"
    elif message.startswith("the argument '"):
        body = message.removeprefix("the argument '").removesuffix("'")
        if "' cannot be used with '" in body:
            first, second = body.split("' cannot be used with '")
            detail = f"error: the argument '{first}' cannot be used with '{second}'"
            usage = f"Usage: varde learn measure <SKILL> flow {first}"
        else:
            detail = f"error: {message}"
    else:
        detail = f"error: {message}"
    if message.startswith("invalid value '"):
        full = f"{detail}\n\nFor more information, try '--help'."
    else:
        full = f"{detail}\n\n{usage}\n\nFor more information, try '--help'."
    if json_error and code:
        print(_json_text(tool_error(code, full + "\n")), file=sys.stderr)
    else:
        print(full, file=sys.stderr)
    return 2


_PAGE_COMMANDS = {"serve", "watch", "comments", "reply", "build"}
_COMMANDS = {
    "lint",
    "frontmatter",
    "flow",
    "spec",
    "how",
    "baseline",
    "blocks",
    "recap",
} | _PAGE_COMMANDS


def run(argv: list[str], io: object | None = None) -> int:
    del io
    args = list(argv)
    if args and args[0] == "doc":
        args.pop(0)
    if not args:
        print(help_text("docs"), end="", file=sys.stderr)
        return 2
    if args in (["--help"], ["-h"]):
        print(help_text("doc"), end="")
        return 0
    command = args.pop(0)
    if command in {"--version", "-V"}:
        print("varde learn docs 1.0.1")
        return 0
    if command in {"-h", "--help"}:
        print(help_text("doc"), end="")
        return 0
    if command not in _COMMANDS:
        print(
            (
                f"error: unrecognized subcommand '{command}'\n\n"
                "Usage: varde learn docs <COMMAND>\n\n"
                "For more information, try '--help'."
            ),
            file=sys.stderr,
        )
        return 2
    try:
        if command == "lint":
            options, paths = _take_options(args, {"json"}, set())
            if not paths:
                _raise(
                    _UsageError(
                        "the following required arguments were not provided: <PATH>..."
                    )
                )
            from .lint import run as lint_run

            return lint_run(
                [Path(path) for path in paths], json_output=bool(options.get("json"))
            )
        if command == "frontmatter":
            options, paths = _take_options(args, {"json"}, set())
            if not paths:
                _raise(
                    _UsageError(
                        "the following required arguments were not provided: <PATH>..."
                    )
                )
            return _run_frontmatter(paths, bool(options.get("json")))
        args_runner = {
            "flow": _run_flow,
            "how": _run_how,
            "baseline": _run_baseline,
            "blocks": _run_blocks,
            "recap": _run_recap,
        }.get(command)
        if args_runner:
            return args_runner(args)
        if command in _PAGE_COMMANDS:
            return _run_pages(command, args)
        return _run_spec(args)
    except SystemExit:
        path = "doc " + command
        if args and command == "flow" and args[0] == "ledger":
            path += " ledger"
        elif args and command == "spec" and args[0] == "inventory":
            path += " inventory"
        print(help_text(path), end="")
        return 0
    except _UsageError as error:
        json_requested = "--json" in args
        return _usage_error(args, command, str(error), json_error=json_requested)


def _run_pages(command: str, args: list[str]) -> int:
    from .pages import cli as pages_cli
    from .pages.comments import KINDS

    flags = {
        "serve": {"open", "allow_edit"},
        "watch": {"all"},
        "comments": {"open", "json"},
    }
    values = {
        "serve": {"port", "host"},
        "watch": {"interval"},
        "reply": {"note"},
        "comments": {"kind"},
        "build": {"out"},
    }
    options, positional = _take_options(
        args,
        flags.get(command, {"json"} if command == "reply" else set()),
        values.get(command, set()),
    )
    names = ["<COMMENT_ID>"] if command == "reply" else []
    missing = (["<DOC>", *names])[len(positional) :]
    if command == "reply" and "note" not in options:
        missing.append("--note <NOTE>")
    if command == "build" and "out" not in options:
        missing.append("--out <FILE>")
    if missing:
        raise _UsageError(
            "the following required arguments were not provided: " + ", ".join(missing)
        )
    if len(positional) > len(names) + 1:
        raise _UsageError(f"unexpected argument '{positional[len(names) + 1]}'")
    doc = Path(positional[0])
    if command == "serve":
        try:
            port = pages_cli.parse_port(str(options.get("port", "0")))
        except ValueError as error:
            raise _UsageError(f"invalid value for '--port <PORT>': {error}") from None
        host = str(options.get("host", "127.0.0.1"))
        return pages_cli.serve_doc(
            doc, port, bool(options.get("open")), host, bool(options.get("allow_edit"))
        )
    if command == "build":
        return pages_cli.build_doc(doc, Path(str(options["out"])))
    if command == "watch":
        return pages_cli.watch_doc(
            doc, str(options.get("interval", "2s")), bool(options.get("all"))
        )
    if command == "comments":
        kind = str(options["kind"]) if "kind" in options else None
        if kind is not None and kind not in KINDS:
            raise _UsageError(
                f"invalid value '{kind}' for '--kind <KIND>': "
                f"expected one of {', '.join(KINDS)}"
            )
        return pages_cli.list_comments(
            doc, bool(options.get("open")), bool(options.get("json")), kind
        )
    return pages_cli.reply_comment(
        doc, positional[1], str(options["note"]), bool(options.get("json"))
    )


def _run_blocks(args: list[str]) -> int:
    from .pages import cli as pages_cli

    options, positional = _take_options(args, set(), {"check"})
    if len(positional) > 1 or (positional and "check" in options):
        raise _UsageError(f"unexpected argument '{positional[-1]}'")
    if "check" in options:
        return pages_cli.check_blocks(Path(str(options["check"])))
    if positional and positional[0] not in pages_cli.block_types():
        raise _UsageError(f"unknown block type '{positional[0]}'")
    return pages_cli.show_blocks(positional[0] if positional else None)


def _run_recap(args: list[str]) -> int:
    from .recap import run as recap_run

    options, positional = _take_options(args, {"json"}, {"base", "head"})
    missing = (["<PLAN>"] if not positional else []) + (
        ["--base <BASE>"] if "base" not in options else []
    )
    if missing:
        raise _UsageError(
            "the following required arguments were not provided: " + ", ".join(missing)
        )
    if len(positional) > 1:
        raise _UsageError(f"unexpected argument '{positional[1]}'")
    return recap_run(
        Path(positional[0]),
        str(options["base"]),
        str(options.get("head", "HEAD")),
        bool(options.get("json")),
    )


def _run_baseline(args: list[str]) -> int:
    options, positional = _take_options(
        args,
        {"json", "check", "record", "provisional"},
        {"baselines", "repo", "source", "gen", "tag", "commit"},
    )
    if not positional or positional[0] != "status":
        raise _UsageError("the following required arguments were not provided: status")
    if "baselines" not in options:
        raise _UsageError(
            "the following required arguments were not provided: --baselines <DIR>"
        )
    if len(positional) > 2:
        raise _UsageError(f"unexpected argument '{positional[2]}'")
    from . import baseline_cmd

    json_output = bool(options.get("json"))
    skill = positional[1] if len(positional) > 1 else None
    source = options.get("source")
    repo = Path(str(source or options.get("repo", ".")))
    try:
        if options.get("record"):
            return _record_baseline(options, repo, skill, bool(source), json_output)
        packages = (
            baseline_cmd.source_packages(repo)
            if source
            else baseline_cmd.provider_packages()
        )
        rows = baseline_cmd.statuses(
            Path(str(options["baselines"])), repo, skill, packages
        )
    except baseline_cmd.BaselineError as error:
        message = f"varde learn measure baseline: {error}"
        print(
            _json_text(tool_error("doc_baseline_input", message))
            if json_output
            else message,
            file=sys.stderr,
        )
        return 2
    if json_output:
        data = [row.to_json() for row in rows]
        print(_json_text(success(data, {"truncated": False})))
    else:
        print(baseline_cmd.render_text(rows))
    return 1 if options.get("check") and baseline_cmd.failed(rows) else 0


def _record_baseline(
    options: dict[str, object],
    repo: Path,
    skill: str | None,
    from_source: bool,
    json_output: bool,
) -> int:
    from . import baseline_cmd

    gen = options.get("gen")
    if not (skill and gen and from_source):
        raise _UsageError(
            "--record needs <SKILL>, --gen <GEN> and --source <DIR> (the checkout)"
        )
    meta = {
        "tag": options.get("tag") or f"skills-nohow-{skill}",
        "commit": options.get("commit") or baseline_cmd.head_commit(repo) or "",
        "date": datetime.now(UTC).date().isoformat(),
        "provisional": bool(options.get("provisional")),
    }
    entry = baseline_cmd.record_baseline(
        Path(str(options["baselines"])), repo, skill, str(gen), meta
    )
    if json_output:
        print(_json_text(success(entry, {"truncated": False})))
    else:
        files_count = len(cast("dict", entry["files"]))
        how_count = len(cast("dict", entry["how"]))
        print(
            f"recorded {skill} baseline {gen}: {files_count} files, "
            f"{how_count} how topics, tree_hash {entry['tree_hash']}"
        )
    return 0


def _run_how(args: list[str]) -> int:
    options, positional = _take_options(args, {"json"}, set())
    if not positional:
        raise _UsageError("the following required arguments were not provided: <SKILL>")
    if len(positional) > 2:
        raise _UsageError(f"unexpected argument '{positional[2]}'")
    from varde_learn.loop.improve import tool_entry

    from . import how_cmd

    json_output = bool(options.get("json"))
    skill, step = positional[0], (positional[1] if len(positional) > 1 else None)
    try:
        topics = how_cmd.all_topics(
            how_cmd.provider_roots(),
            how_cmd.agent_roots(),
            how_cmd.load_installed_topics(tool_entry.installed_roots()),
        )
    except (ValueError, TypeError) as error:
        message = f"varde learn how: {error}"
        print(
            _json_text(tool_error("doc_how_input", message))
            if json_output
            else message,
            file=sys.stderr,
        )
        return 2
    steps = topics.get(skill, {})
    if skill not in topics or (step is not None and step not in steps):
        message = how_cmd.valid_ids_message(topics, skill, step)
        print(
            _json_text(tool_error("doc_how_unknown", message))
            if json_output
            else f"error: {message}",
            file=sys.stderr,
        )
        return 1
    if step is None:
        rows = [steps[name] for name in sorted(steps)]
        if json_output:
            data = {
                "skill": skill,
                "steps": [how_cmd.topic_json(r, with_body=False) for r in rows],
            }
            print(_json_text(success(data, {"truncated": False})))
        else:
            print("\n".join(how_cmd.step_line(row) for row in rows))
        return 0
    chosen = steps[step]
    if json_output:
        print(
            _json_text(
                success(
                    how_cmd.topic_json(chosen, with_body=True), {"truncated": False}
                )
            )
        )
    else:
        print(chosen.body)
    return 0


def _run_frontmatter(paths: list[str], json_output: bool) -> int:
    from .frontmatter import InputError, check, render_text

    try:
        results = check(paths)
    except InputError as error:
        message = (
            tool_error("doc_frontmatter_input", str(error))
            if json_output
            else str(error)
        )
        print(_json_text(message) if json_output else message, file=sys.stderr)
        return 2
    failed = sum(not result.ok for result in results)
    data = {"results": [result.to_json() for result in results]}
    if json_output:
        meta = {"truncated": False}
        if failed:
            message = (
                f"{failed} of {len(results)} skill(s) failed frontmatter validation"
            )
            envelope = negative_result("doc_frontmatter_failed", message, data, meta)
        else:
            envelope = success(data, meta)
        print(_json_text(envelope))
    else:
        print(render_text(results), end="")
    return 1 if failed else 0


def _run_flow(args: list[str]) -> int:
    if args and args[0] == "ledger":
        return _run_ledger(args[1:])
    options, paths = _take_options(args, {"mermaid", "json", "write", "check"}, set())
    if not paths:
        raise _UsageError(
            "the following required arguments were not provided: <SKILL_DIR>..."
        )
    selected = [
        token[2:]
        for token in args
        if token.startswith("--")
        and "=" not in token
        and token[2:] in {"mermaid", "json", "write", "check"}
    ]
    if len(selected) > 1:
        raise _UsageError(
            f"the argument '--{selected[0]}' cannot be used with '--{selected[-1]}'"
        )
    from .flow.analyze import analyze_skill, resolve_local_main_costs
    from .flow.render import flow_doc, mermaid, text_report

    skills = []
    path = paths[0]
    try:
        for path in paths:
            if not Path(path).is_dir():
                raise FileNotFoundError(2, "not a skill directory", path)
            skills.append(resolve_local_main_costs(analyze_skill(Path(path))))
    except OSError as error:
        message = (
            f"varde learn measure flow: not a skill directory: {path}"
            if getattr(error, "errno", None) == 2
            else f"varde learn measure flow: {path}: {error}"
        )
        return _flow_error(bool(options.get("json")), message)
    if options.get("write") or options.get("check"):
        stale = 0
        for path, skill in zip(paths, skills, strict=False):
            target = Path(path) / "FLOW.md"
            doc = flow_doc(skill)
            if options.get("write"):
                try:
                    target.write_text(doc, encoding="utf-8")
                except OSError as error:
                    return _flow_error(
                        bool(options.get("json")),
                        f"varde learn measure flow: {target}: {error}",
                    )
            elif not target.is_file() or target.read_text(encoding="utf-8") != doc:
                stale += 1
                print(f"stale: {target} (run varde learn check --write {Path(path)})")
        return 1 if stale else 0
    failed = any(skill.findings.missing for skill in skills)
    if options.get("json"):
        data = [_flow_json(skill) for skill in skills]
        envelope = success(data, {"truncated": False})
        if failed:
            missing = sum(len(skill.findings.missing) for skill in skills)
            envelope = negative_result(
                "doc_flow_missing",
                f"{missing} missing file(s) across {len(skills)} skill(s)",
                data,
                {"truncated": False},
            )
        print(_json_text(envelope))
    else:
        render = mermaid if options.get("mermaid") else text_report
        print("\n\n".join(render(skill) for skill in skills))
    return 1 if failed else 0


def _flow_error(json_output: bool, message: str) -> int:
    print(
        _json_text(tool_error("doc_flow_input", message)) if json_output else message,
        file=sys.stderr,
    )
    return 2


def _flow_json(value):
    from .flow.model import ROUTE_ABSENT, Edge, External, ExternalType, OrderedMap, Runs

    if isinstance(value, OrderedMap):
        return {key: _flow_json(item) for key, item in value.iter()}
    if isinstance(value, Runs):
        if value.file is not None:
            return {"file": value.file}
        return {"skill": value.skill, "mode": value.mode}
    if isinstance(value, Edge):
        result = {
            "from": value.from_,
            "to": value.to,
            "context": value.context,
            "conditional": value.conditional,
            "kind": value.kind,
            "table": value.table,
            "line": value.line,
        }
        if value.route is not ROUTE_ABSENT:
            result["route"] = value.route
        return result
    if isinstance(value, External):
        result = {
            "from": value.from_,
            "external": value.external,
            "target": value.target,
        }
        if value.external == ExternalType.SKILL:
            result.update(
                {
                    "skill": value.skill,
                    "mode": value.mode,
                    "context": value.context,
                    "conditional": value.conditional,
                    "kind": value.kind,
                    "table": value.table,
                    "line": value.line,
                }
            )
            if value.qualifier is not None:
                result["qualifier"] = value.qualifier
        else:
            result.update(
                {
                    "runs": _flow_json(value.runs),
                    "context": value.context,
                    "conditional": value.conditional,
                    "table": value.table,
                    "line": value.line,
                }
            )
        if value.route is not ROUTE_ABSENT:
            result["route"] = value.route
        return result
    if is_dataclass(value):
        names = {"single_caller": "single caller", "fan_out": "fan-out"}
        result = {}
        for field in fields(value):
            item = getattr(value, field.name)
            if (
                type(value).__name__ == "Structure"
                and field.name.startswith("max_route_")
                and item is None
            ):
                continue
            result[names.get(field.name, field.name.removesuffix("_"))] = _flow_json(
                item
            )
        return result
    if isinstance(value, dict):
        return {key: _flow_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_flow_json(item) for item in value]
    return value


def _run_ledger(args: list[str]) -> int:
    if len(args) == 1 and args[0] in {"--help", "-h"}:
        print(help_text("doc flow ledger"), end="")
        return 0
    if not args:
        raise _UsageError(
            "the following required arguments were not provided: <ACTION>, <LEDGER>"
        )
    action_names = tuple(action.value for action in LedgerAction)
    action_index = next(
        (index for index, token in enumerate(args) if token in action_names), None
    )
    if action_index is None:
        if args and not args[0].startswith("-"):
            values = ", ".join(action_names)
            raise _UsageError(
                f"invalid value '{args[0]}' for '<ACTION>'\n"
                f"  [possible values: {values}]"
            )
        raise _UsageError("a value is required for '<ACTION>'")
    action = LedgerAction(args[action_index])
    command_args = args[:action_index] + args[action_index + 1 :]
    options, positional = _take_options(command_args, {"json"}, {"root", "route"})
    if len(positional) != 1:
        raise _UsageError("the following required argument was not provided: <LEDGER>")
    from .flow.ledger import _load, check, hash_ledger, score, validate

    ledger_path = Path(positional[0])
    try:
        data = _load(ledger_path)
        root_option = options.get("root")
        root = Path(cast("str", root_option)) if root_option else _git_root()
        json_output = bool(options.get("json"))
        if action is LedgerAction.SCORE:
            result = score(data, cast("str | None", options.get("route")))
            if json_output:
                print(_json_text(success(result, {"truncated": False})))
            else:
                print(
                    f"cyclomatic {result['cyclomatic']} cognitive "
                    f"{result['cognitive']} decisions {result['decisions']} "
                    f"branch_units {result['branch_units']}"
                )
                for name, row in result["phases"].items():
                    print(
                        f"  {name}: {row['decisions']} decisions, "
                        f"{row['branch_units']} units, cognitive {row['cognitive']}"
                    )
            return 0
        if action is LedgerAction.HASH:
            count = hash_ledger(data, root)
            ledger_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
            )
            if json_output:
                print(_json_text(success({"hashed": count}, {"truncated": False})))
            return 0
        found = (
            validate(data, root)
            if action is LedgerAction.VALIDATE
            else check(data, root)
        )
        key, code = (
            ("problems", "doc_ledger_problems")
            if action is LedgerAction.VALIDATE
            else ("stale", "doc_ledger_stale")
        )
        if json_output:
            envelope = (
                success({key: found}, {"truncated": False})
                if not found
                else negative_result(
                    code, f"{len(found)} {key}", {key: found}, {"truncated": False}
                )
            )
            print(_json_text(envelope))
        elif found:
            print("\n".join(found))
    except (OSError, ValueError, TypeError, KeyError) as error:
        if action is LedgerAction.HASH:
            print(f"{error}", file=sys.stderr)
            return 1
        message = (
            "stream did not contain valid UTF-8"
            if isinstance(error, UnicodeDecodeError)
            else f"varde learn measure ledger: {error}"
        )
        if isinstance(error, OSError) and error.filename:
            message = (
                f"varde learn measure ledger: {error.filename}: {error.strerror} "
                f"(os error {error.errno})"
            )
        if options.get("json"):
            print(
                _json_text(tool_error("doc_flow_ledger_input", message)),
                file=sys.stderr,
            )
        else:
            print(message, file=sys.stderr)
        return 2
    else:
        return 1 if found else 0


def _git_root() -> Path:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH as the repository tool.
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else Path.cwd()


def _run_spec(args: list[str]) -> int:
    if args and args[0] in {"--help", "-h"}:
        raise SystemExit(0)
    if not args:
        print(help_text("doc spec"), end="", file=sys.stderr)
        return 2
    if args[0] != "inventory":
        raise _UsageError("a subcommand is required")
    if len(args) > 1 and args[1] in {"--help", "-h"}:
        raise SystemExit(0)
    options, positional = _take_options(
        args[1:],
        {"refresh", "json"},
        {"repository", "knowledge", "working", "acknowledge_architecture_path"},
    )
    if positional:
        raise _UsageError(f"unexpected argument '{positional[0]}'")
    missing = [
        name for name in ("repository", "knowledge", "working") if name not in options
    ]
    if missing:
        raise _UsageError(
            "the following required arguments were not provided: "
            + ", ".join(
                f"--{name.replace('_', '-')} <{name.upper()}>" for name in missing
            )
        )
    from . import spec_inventory

    try:
        result = spec_inventory.inventory(
            Path(cast("str", options["repository"])),
            Path(cast("str", options["knowledge"])),
            Path(cast("str", options["working"])),
            refresh=bool(options.get("refresh")),
            acknowledge_architecture_paths=[
                str(path)
                for path in cast(
                    "list[Path]", options.get("acknowledge_architecture_paths", [])
                )
            ],
        )
    except (OSError, ValueError, RuntimeError) as error:
        if isinstance(error, FileNotFoundError):
            print(
                (
                    "Error: repository does not exist\n\nCaused by:\n    "
                    "No such file or directory (os error 2)"
                ),
                file=sys.stderr,
            )
        else:
            print(f"Error: {error!r}", file=sys.stderr)
        return 1
    print(
        _json_text(
            success(result, {"truncated": False}) if options.get("json") else result
        )
    )
    return 0
