"""CLI handlers exposed by the knowledge module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from varde_core.memory_dirs import legacy_memory_bank_dirs

from varde_learn.knowledge import memory
from varde_learn.knowledge.cmdbase import (
    CliError,
    InternalError,
    page_bounds,
    pagination_meta,
    print_cli_failure_with_meta,
    print_cli_success,
    print_cli_success_with_meta,
    read_input,
    report_cli_error,
    resolve_bundle,
)
from varde_learn.knowledge.concept import slug_from_filename
from varde_learn.knowledge.crud import concept_path_or
from varde_learn.knowledge.crud.create import CreateError, create
from varde_learn.knowledge.crud.delete import DeleteError, delete
from varde_learn.knowledge.crud.list import ListError
from varde_learn.knowledge.crud.list import list as list_concepts
from varde_learn.knowledge.crud.search import TextSearchResult, search_text_matching
from varde_learn.knowledge.crud.show import ShowError, ShownConcept, show
from varde_learn.knowledge.crud.timestamps import git_created_updated
from varde_learn.knowledge.crud.update import UpdateError, update
from varde_learn.knowledge.frontmatter import FrontmatterError, parse, serialize
from varde_learn.knowledge.lint import (
    LintError,
    LintOptions,
    Severity,
    lint_with_options,
)
from varde_learn.knowledge.maps import MapError
from varde_learn.knowledge.maps import generate as generate_maps
from varde_learn.knowledge.memory import MemoryPaths
from varde_learn.knowledge.memory_config import load_config, save_config
from varde_learn.knowledge.occ import version
from varde_learn.knowledge.registry import RegistryError
from varde_learn.knowledge.registry import search as registry_search


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


class _CodedError(CliError):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        input_errors = {
            "invalid_slug",
            "missing_description",
            "invalid_description",
            "invalid_aliases",
            "missing_type",
            "invalid_type",
            "reserved_structured_field",
        }
        self.code = "invalid_input" if code in input_errors else code
        self.status = 4 if status is None and code in input_errors else status

    def error_code(self) -> str:
        return self.code

    def exit_code(self) -> int:
        if self.status is not None:
            return self.status
        if self.code == "conflict":
            return 3
        if self.code == "not_found":
            return 2
        if self.code == "already_exists":
            return 5
        return 1


report_error = report_cli_error


def _parser() -> _Parser:
    parser = _Parser(prog="varde", add_help=False)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_Parser
    )
    concept = commands.add_parser("concept", add_help=False)
    concept_commands = concept.add_subparsers(
        dest="concept_command", required=True, parser_class=_Parser
    )

    create_parser = concept_commands.add_parser("create", add_help=False)
    create_parser.add_argument("--bundle", required=True)
    create_parser.add_argument("--file")
    create_parser.add_argument("slug", nargs="?")
    create_parser.add_argument("--json", action="store_true")

    show_parser = concept_commands.add_parser("show", add_help=False)
    show_parser.add_argument("--bundle", required=True)
    show_parser.add_argument("slug")
    show_parser.add_argument("--frontmatter-only", action="store_true")
    show_parser.add_argument("--json", action="store_true")

    update_parser = concept_commands.add_parser("update", add_help=False)
    update_parser.add_argument("--bundle", required=True)
    update_parser.add_argument("slug")
    update_parser.add_argument("--expected-version", required=True)
    update_parser.add_argument("--file")
    update_parser.add_argument("--json", action="store_true")

    list_parser = concept_commands.add_parser("list", add_help=False)
    _add_bundle(list_parser)
    list_parser.add_argument("--include-deprecated", action="store_true")
    _add_page(list_parser)
    list_parser.add_argument("--json", action="store_true")

    delete_parser = concept_commands.add_parser("delete", add_help=False)
    delete_parser.add_argument("--bundle", required=True)
    delete_parser.add_argument("slug")
    delete_parser.add_argument("--json", action="store_true")

    search_parser = concept_commands.add_parser("search", add_help=False)
    search_parser.add_argument("--field", action="append", default=[])
    search_parser.add_argument("--text")
    search_parser.add_argument("--limit", type=int, default=20)
    _add_bundle(search_parser)
    search_parser.add_argument("--json", action="store_true")

    field_parser = concept_commands.add_parser("set-field", add_help=False)
    field_parser.add_argument("--bundle", required=True)
    field_parser.add_argument("slug")
    field_parser.add_argument("key")
    field_parser.add_argument("value")
    field_parser.add_argument("--expected-version", required=True)
    field_parser.add_argument("--json", action="store_true")

    lint_parser = commands.add_parser("lint", add_help=False)
    _add_bundle(lint_parser)
    lint_parser.add_argument("--require-index", action="store_true")
    _add_page(lint_parser)
    lint_parser.add_argument("--json", action="store_true")

    map_parser = commands.add_parser("map", add_help=False)
    _add_bundle(map_parser)
    map_parser.add_argument("--json", action="store_true")

    paths_parser = commands.add_parser("paths", add_help=False)
    paths_parser.add_argument("--project")
    paths_parser.add_argument("--json", action="store_true")
    paths_commands = paths_parser.add_subparsers(
        dest="paths_command", parser_class=_Parser
    )
    paths_set = paths_commands.add_parser("set", add_help=False)
    _add_paths_options(paths_set, unset=False)
    paths_unset = paths_commands.add_parser("unset", add_help=False)
    _add_paths_options(paths_unset, unset=True)
    return parser


PATH_FIELDS = ("working", "knowledge", "toz")
GLOBAL_PATH_FIELDS = ("learn", "memory")  # always written to `[default]`


def _add_bundle(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bundle")


def _add_page(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=_positive_integer, default=100)
    parser.add_argument("--offset", type=_nonnegative_integer, default=0)
    parser.add_argument("--all", action="store_true")


def _add_paths_options(parser: argparse.ArgumentParser, *, unset: bool) -> None:
    for name in (*PATH_FIELDS, *GLOBAL_PATH_FIELDS):
        if unset:
            parser.add_argument(f"--{name}", action="store_true")
        else:
            parser.add_argument(f"--{name}")
    parser.add_argument("--default", action="store_true")
    parser.add_argument("--project", default=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return parsed


def run(argv: list[str], io: object = None) -> int:
    """Run one app-routed command. The route prefix is already removed."""
    help_path = _help_path(argv)
    if help_path is not None:
        try:
            sys.stdout.write(help_text(help_path))
        except KeyError as exc:
            return report_error(CliError(str(exc)), False)
        else:
            return 0
    try:
        args = _parser().parse_args(argv)
    except (ValueError, argparse.ArgumentError) as exc:
        return _report_parser_error(argv, str(exc))
    try:
        _refuse_if_migrated(args)
        if args.command == "concept":
            return _run_concept(args)
        if args.command == "lint":
            return _run_lint(args)
        if args.command == "map":
            return _run_map(args)
        if args.command == "paths":
            return _run_paths(args)
        return report_error(CliError(f"unknown command: {args.command}"), False)
    except (
        CreateError,
        ShowError,
        UpdateError,
        DeleteError,
        ListError,
        RegistryError,
    ) as exc:
        code = getattr(exc, "kind", "internal")
        message = str(exc)
        status = None
        slug = getattr(exc, "slug", None)
        if isinstance(exc, CreateError) and code == "invalid_concept":
            code = "internal"
            status = 1
        elif code == "invalid_slug":
            code = "invalid_input"
            status = 4
            message = (
                f"invalid slug `{slug}`: must be kebab-case path segments, e.g. "
                "`my-concept` or `pattern/my-concept`"
            )
        elif code == "already_exists":
            code = "already_exists"
            status = 5
            message = f"concept `{slug}` already exists in the bundle"
        elif code == "not_found":
            message = f"concept `{slug}` not found in the bundle"
        elif code in {
            "missing_description",
            "invalid_description",
            "invalid_aliases",
            "missing_type",
            "invalid_type",
            "reserved_structured_field",
        }:
            code = "invalid_input"
            status = 4
        elif code == "invalid_concept" and getattr(exc, "path", None) is not None:
            if isinstance(exc, ShowError):
                message = str(getattr(exc, "source", exc))
                code = "internal"
                status = 1
            else:
                message = (
                    f"`{exc.path}` is not a valid concept: "
                    f"{getattr(exc, 'source', exc)}"
                )
                if isinstance(exc, (ListError, RegistryError)):
                    code = "internal"
                    status = 1
                else:
                    code = "invalid_input"
                    status = 4
        elif isinstance(exc, UpdateError) and code == "conflict":
            try:
                actual = version(exc.path.read_bytes()) if exc.path else ""
            except OSError:
                actual = ""
            expected = getattr(args, "expected_version", "")
            message = (
                f"version conflict for `{exc.slug}`: expected {expected} but the "
                f"file is at {actual}; it changed since it was read — re-read and retry"
            )
        return report_error(
            _CodedError(code, message, status), bool(getattr(args, "json", False))
        )
    except CliError as exc:
        return report_error(exc, bool(getattr(args, "json", False)))
    except (OSError, ValueError, FrontmatterError) as exc:
        message = str(exc)
        if isinstance(exc, LintError):
            source = exc.source
            source_text = (
                f"{source.strerror} (os error {source.errno})"
                if source.errno is not None and source.strerror
                else str(source)
            )
            message = f"failed to read bundle directory `{exc.path}`: {source_text}"
        elif isinstance(exc, OSError) and exc.errno is not None and exc.strerror:
            message = f"{exc.strerror} (os error {exc.errno})"
            path = getattr(exc, "filename", None)
            if path and isinstance(exc, FileNotFoundError):
                message = f"failed to read bundle directory `{path}`: {message}"
        return report_error(InternalError(message), bool(getattr(args, "json", False)))


def _report_parser_error(argv: list[str], message: str) -> int:
    route = argv[:2] if argv and argv[0] == "concept" else argv[:1]
    help_route = _help_route(route)
    try:
        usage = next(
            line
            for line in help_text(help_route).splitlines()
            if line.startswith("Usage:")
        ).replace(" [OPTIONS]", "")
    except KeyError, StopIteration:
        usage = "Usage: varde"

    lines = []
    if message.startswith("the following arguments are required:"):
        missing = message.partition(":")[2].strip().split(", ")
        labels = [
            f"{item} <{item[2:].replace('-', '_').upper()}>"
            if item.startswith("--")
            else f"<{item.upper()}>"
            for item in missing
        ]
        lines.extend(
            (
                "error: the following required arguments were not provided:",
                *(f"  {label}" for label in labels),
            )
        )
        if route == ["concept", "create"] and "--json" in argv:
            usage = (
                "Usage: varde learn knowledge create --bundle <BUNDLE> --json [SLUG]"
            )
    elif message.startswith("unrecognized arguments:"):
        unexpected = message.partition(":")[2].strip().split()
        argument = next(
            (item for item in unexpected if item.startswith("-")),
            unexpected[0] if unexpected else "",
        )
        lines.append(f"error: unexpected argument '{argument}' found")
        if argument.startswith("--"):
            lines.extend(
                ("", f"  tip: to pass '{argument}' as a value, use '-- {argument}'")
            )
    else:
        lines.append(f"error: {message}")
    lines.extend(("", usage, "", "For more information, try '--help'."))
    print("\n".join(lines), file=sys.stderr)
    return 2


def _help_path(argv: list[str]) -> str | None:
    if "--help" not in argv and "-h" not in argv:
        return None
    route = argv[
        : min(
            (index for index, value in enumerate(argv) if value in {"--help", "-h"}),
            default=len(argv),
        )
    ]
    if not route or route[0] not in {"concept", "lint", "map", "paths"}:
        return None
    return _help_route(route)


def _help_route(route: list[str]) -> str:
    """Name the help snapshot for the internal argv route."""
    if route[:1] == ["paths"]:
        return " ".join(("setup", *route))
    if route[:1] == ["concept"]:
        verb = "search" if route[1:] == ["list"] else " ".join(route[1:])
        return f"knowledge {verb}".strip()
    return " ".join(("knowledge", *route))


def _run_concept(args: argparse.Namespace) -> int:
    command = args.concept_command
    if command == "create":
        if bool(args.file) == bool(args.slug):
            return report_error(
                CliError(
                    (  # noqa: UP034 - Explicit grouping is required for split usage text.
                        "knowledge create requires exactly one of `--file <path>` or "
                        "a positional <slug> with the document on stdin"
                    )
                ),
                args.json,
            )
        if args.file:
            name = Path(args.file).name
            slug = slug_from_filename(name)
            if slug is None:
                return report_error(
                    CliError("input file must be named `<slug>.md` (kebab-case slug)"),
                    args.json,
                )
            data = read_input(args.file)
        else:
            slug = args.slug
            data = read_input()
        created = create(resolve_bundle(args.bundle), data, slug)
        if args.json:
            print_cli_success({"slug": created.slug, "version": created.version})
        else:
            print(f"created {created.slug} (version {created.version})")
        return 0
    if command == "show":
        bundle = resolve_bundle(args.bundle)
        concept = _migrated_concept(bundle, args.slug)
        from_store = concept is not None
        concept = concept or show(bundle, args.slug)
        if args.frontmatter_only:
            print(
                json.dumps(
                    concept.frontmatter,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        created, updated = (
            (None, None) if from_store else git_created_updated(args.bundle, args.slug)
        )
        if args.json:
            print_cli_success(
                {
                    "slug": concept.slug,
                    "version": concept.version,
                    "frontmatter": concept.frontmatter,
                    "body": concept.body,
                    "created": created,
                    "updated": updated,
                }
            )
        else:
            from varde_learn.knowledge.formats import dump_yaml

            rendered = dump_yaml(concept.frontmatter)
            rendered = rendered.removeprefix("---\n")
            print("---")
            print(rendered, end="" if rendered.endswith("\n") else "\n")
            print("---")
            print(concept.body, end="" if concept.body.endswith("\n") else "\n")
            print(f"\nversion: {concept.version}")
            if created:
                print(f"created: {created}")
            if updated:
                print(f"updated: {updated}")
        return 0
    if command == "update":
        data = read_input(args.file)
        updated = update(
            resolve_bundle(args.bundle), args.slug, args.expected_version, data
        )
        if args.json:
            print_cli_success(
                {
                    "slug": updated.slug,
                    "old_version": updated.old_version,
                    "new_version": updated.new_version,
                }
            )
        else:
            print(
                (  # noqa: UP034 - Explicit grouping is required for split output text.
                    f"updated {updated.slug} (version {updated.old_version} -> "
                    f"{updated.new_version})"
                )
            )
        return 0
    if command == "list":
        return _run_list(args)
    if command == "delete":
        slug = delete(resolve_bundle(args.bundle), args.slug)
        if args.json:
            print_cli_success({"slug": slug, "deleted": True})
        else:
            print(f"deleted {slug}")
        return 0
    if command == "search":
        return _run_search(args)
    if command == "set-field":
        return _run_set_field(args)
    return report_error(CliError(f"unknown knowledge command: {command}"), args.json)


def _run_list(args: argparse.Namespace) -> int:
    bundle = resolve_bundle(args.bundle)
    concepts = list_concepts(bundle, args.include_deprecated)
    start, end = page_bounds(len(concepts), args.offset, args.limit, args.all)
    selected = concepts[start:end]
    if args.json:
        print_cli_success_with_meta(
            [item.as_dict() for item in selected],
            pagination_meta(len(concepts), start, end, args.limit, args.all),
        )
    elif not concepts:
        print("no concepts in bundle")
    else:
        for item in selected:
            print(f"{item.slug}\t{item.type_ or ''}")
        if end < len(concepts):
            print(
                (
                    f"showing {end - start} of {len(concepts)} concepts; continue "
                    f"with --offset {end}"
                ),
                file=sys.stderr,
            )
    return 0


def _run_search(args: argparse.Namespace) -> int:
    filters = _parse_filters(args.field)
    bundle = resolve_bundle(args.bundle)
    if args.text is None:
        entries = registry_search([bundle], filters)
        values = [entry.as_dict() for entry in entries]
        if args.json:
            print_cli_success(values)
        elif not entries:
            print("no concepts match")
        else:
            for entry in entries:
                print(f"{entry.slug}\t{entry.type_ or ''}")
        return 0
    results = _migrated_results(bundle, args.text, filters, args.limit)
    if results is None:
        results = search_text_matching([bundle], args.text, filters, args.limit)
    values = [item.as_dict() for item in results]
    if args.json:
        print_cli_success(values)
    elif not results:
        print("no concepts match")
    else:
        for item in results:
            print(f"{item.slug}\t{item.type_ or ''}\t{item.score}\t{item.preview}")
    return 0


def _migrated_concept(bundle: Path, slug: str) -> ShownConcept | None:
    """A migrated bundle's concept as read from the unified store, else None."""
    from varde_learn.memory import migrated, store

    return migrated.shown_concept(store.memory_root(Path.cwd()), bundle, slug)


def _migrated_results(
    bundle: Path, text: str, filters: list[tuple[str, str]], limit: int
) -> list[TextSearchResult] | None:
    """Text hits from the unified store when the bundle was migrated, else None."""
    from varde_learn.memory import migrated, search, store

    root = store.memory_root(Path.cwd())
    source = migrated.migrated_source(root, bundle)
    if source is None:
        return None
    options = search.SearchOptions(
        filters=tuple(filters), limit=limit, include_expired=True
    )
    entries = {str(source.path_of(e)): e for e in source.load()[0]}
    return [
        TextSearchResult(
            migrated.original_slug(entries[str(hit.path)], bundle),
            hit.type,
            hit.score,
            hit.preview,
        )
        for hit in search.search_substring(source, text, options)
    ]


_MIGRATED_REFUSED = {"create", "update", "delete", "set-field"}


def _refuse_if_migrated(args: argparse.Namespace) -> None:
    """A migrated bundle changes only through `memory`, so the bundle is not edited."""
    if args.command != "concept" or args.concept_command not in _MIGRATED_REFUSED:
        return
    from varde_learn.memory import migration_record, store

    bundle = resolve_bundle(args.bundle)
    if migration_record.read_record(store.memory_root(Path.cwd()), bundle) is None:
        return
    verb = {"create": "add"}.get(args.concept_command, args.concept_command)
    raise _CodedError(
        "invalid_input",
        f"bundle `{bundle}` was migrated; use `varde learn memory {verb}`",
        4,
    )


def _parse_filters(fields: list[str]) -> list[tuple[str, str]]:
    filters: list[tuple[str, str]] = []
    for field in fields:
        key, separator, value = field.partition("=")
        if not separator or not key:
            raise _CodedError(
                "invalid_input", f"invalid --field `{field}`: expected `key=value`"
            )
        filters.append((key, value))
    return filters


def _run_set_field(args: argparse.Namespace) -> int:
    bundle = resolve_bundle(args.bundle)
    path = concept_path_or(bundle, args.slug)
    current = path.read_bytes()
    actual = version(current)
    if actual != args.expected_version:
        raise _CodedError(
            "conflict",
            (
                f"version conflict for `{args.slug}`: expected "
                f"{args.expected_version} but the file is at {actual}; "
                "it changed since it was read — re-read and retry"
            ),
        )
    frontmatter, body = parse(current)
    structured = {
        "sources",
        "verified",
        "generated",
        "stale_after",
        "runtime",
        "builder",
        "attester",
    }
    if args.key == "type" and not args.value:
        raise _CodedError(
            "invalid_type",
            (
                "`type` must be a non-empty string and can never be removed: "
                "it is the required identity field"
            ),
        )
    if args.key in structured:
        raise _CodedError(
            "reserved_structured_field",
            (
                f"`{args.key}` is a structured list/object field and cannot be "
                "overwritten with a bare scalar value"
            ),
        )
    frontmatter[args.key] = args.value
    if not isinstance(frontmatter.get("type"), str) or not frontmatter["type"]:
        raise _CodedError(
            "missing_type", "concept is missing the required `type` field"
        )
    updated = update(bundle, args.slug, actual, serialize(frontmatter, body).encode())
    if args.json:
        print_cli_success(
            {
                "slug": args.slug,
                "key": args.key,
                "value": args.value,
                "old_version": updated.old_version,
                "new_version": updated.new_version,
            }
        )
    else:
        print(
            (  # noqa: UP034 - Explicit grouping is required for split output text.
                f"set {args.key}={args.value} on {args.slug} "
                f"(version {updated.old_version} -> {updated.new_version})"
            )
        )
    return 0


def _run_lint(args: argparse.Namespace) -> int:
    bundle = resolve_bundle(args.bundle)
    report = lint_with_options(bundle, LintOptions(require_index=args.require_index))
    has_errors = any(issue.severity is Severity.ERROR for issue in report.issues)
    start, end = page_bounds(len(report.issues), args.offset, args.limit, args.all)
    selected = report.issues[start:end]
    if args.json:
        issues = [
            {
                "severity": item.severity.value,
                "check_kind": item.check_kind.value,
                "path": str(item.path),
                "message": item.message,
            }
            for item in selected
        ]
        meta = pagination_meta(len(report.issues), start, end, args.limit, args.all)
        if has_errors:
            print_cli_failure_with_meta(
                "validation_failed", "bundle lint found errors", issues, meta
            )
        else:
            print_cli_success_with_meta(issues, meta)
    else:
        for issue in selected:
            print(f"{issue.severity.value}: {issue.message}")
        if end < len(report.issues):
            print(
                (
                    f"showing {end - start} of {len(report.issues)} issues; continue "
                    f"with --offset {end}"
                ),
                file=sys.stderr,
            )
    return int(has_errors)


def _run_map(args: argparse.Namespace) -> int:
    try:
        generated = generate_maps(resolve_bundle(args.bundle))
    except MapError as exc:
        raise CliError(str(exc)) from exc
    if args.json:
        print_cli_success(generated.as_dict())
        return 0
    print(f"wrote {generated.root} and {len(generated.type_maps)} type maps")
    print(f"{generated.entries} concepts")
    return 0


def _run_paths(args: argparse.Namespace) -> int:
    command = args.paths_command
    if command is None:
        return _show_paths(args)
    if args.paths_command == "set":
        return _edit_paths(args, unset=False)
    return _edit_paths(args, unset=True)


def _project_root(project: str | None) -> Path:
    if project is not None:
        root = Path(project)
    else:
        cwd = Path.cwd()
        root = memory.find_root(cwd) or cwd
    return memory.repository_memory_root(root)


def _show_paths(args: argparse.Namespace) -> int:
    root = _project_root(args.project)
    paths = MemoryPaths.resolve(root)
    if args.json:
        print_cli_success(_resolved_paths_data(paths, paths.config))
    else:
        print(f"root: {paths.root}")
        print(f"working: {paths.working.path} ({paths.working.source.value})")
        print(f"knowledge: {paths.knowledge.path} ({paths.knowledge.source.value})")
        print(f"memory: {paths.memory.path} ({paths.memory.source.value})")
        print(f"learn: {paths.learn.path} ({paths.learn.source.value})")
        print(
            f"toz: {paths.toz.path} ({paths.toz.source.value})"
            if paths.toz
            else "toz: (unset)"
        )
        print(f"config: {paths.config}")
        legacy = _legacy_memory_bank(paths)
        if legacy:
            print(_legacy_hint(paths.root, legacy))
    return 0


def _legacy_memory_bank(paths: MemoryPaths) -> list[str]:
    resolved = {paths.working.path, paths.knowledge.path}
    return [
        str(path)
        for path in legacy_memory_bank_dirs(paths.root)
        if memory.canonical_or_lexical(path) not in resolved
    ]


def _legacy_hint(root: Path, legacy: list[str]) -> str:
    return (
        f"legacy memory-bank found (no longer used by default): {', '.join(legacy)}\n"
        "  Move the contents to the paths above by hand, or keep them with:\n"
        f"  varde setup paths set --project {root} --working memory-bank/working"
        " --knowledge memory-bank/knowledge"
    )


def _edit_paths(args: argparse.Namespace, *, unset: bool) -> int:
    fields = (*PATH_FIELDS, *GLOBAL_PATH_FIELDS)
    supplied = [name for name in fields if getattr(args, name)]
    global_names = [name for name in GLOBAL_PATH_FIELDS if getattr(args, name)]
    if not supplied:
        return report_error(
            InternalError(
                "pass --working, --knowledge, --toz, --learn, and/or --memory"
            ),
            args.json,
        )
    for name in global_names:
        if not unset and not getattr(args, name).strip():
            return report_error(
                InternalError(f"--{name} must be a non-empty path"), args.json
            )
    if global_names and any(getattr(args, n) for n in PATH_FIELDS) and not args.default:
        return report_error(
            InternalError(
                f"combine --{'/--'.join(global_names)} with other path options "
                "only with --default"
            ),
            args.json,
        )
    if args.default and args.project:
        return report_error(
            InternalError("--default conflicts with --project"), args.json
        )
    config = load_config()
    root = None if args.default or global_names else _project_root(args.project)
    entry, parent, entry_key = _config_entry(config.document, root)
    for name in supplied:
        key = name
        if unset:
            entry.pop(key, None)
        else:
            entry[key] = getattr(args, name)
    if root is not None and not entry:
        del parent[entry_key]
        if not parent:
            config.document.pop("project", None)
    if root is None and not entry:
        config.document.pop("default", None)
    config_path_value = save_config(config)
    if root is None:
        if args.json:
            print_cli_success(
                {
                    "default": {
                        key: config.document.get("default", {}).get(key)
                        for key in fields
                        if key != "memory"
                        or "memory" in config.document.get("default", {})
                    },
                    "config": str(config_path_value),
                }
            )
        else:
            print(f"updated {config_path_value}")
    else:
        paths = MemoryPaths.resolve_with(root, config)
        if args.json:
            print_cli_success(_resolved_paths_data(paths, config_path_value))
        else:
            print(f"updated {config_path_value}")
            print(f"working: {paths.working.path}")
            print(f"knowledge: {paths.knowledge.path}")
            print(f"learn: {paths.learn.path}")
            print(f"toz: {paths.toz.path}" if paths.toz else "toz: (unset)")
    return 0


def _config_entry(document: Any, root: Path | None) -> tuple[Any, Any, str]:
    if root is None:
        entry = document.get("default")
        if entry is None:
            entry = {}
            document["default"] = entry
        return entry, document, "default"
    project = document.get("project")
    if project is None:
        project = {}
        document["project"] = project
    entry_key = next(
        (key for key in project if memory.canonical_or_lexical(Path(str(key))) == root),
        str(root),
    )
    entry = project.get(entry_key)
    if entry is None:
        entry = {}
        project[entry_key] = entry
    return entry, project, entry_key


def _resolved_paths_data(paths: MemoryPaths, config: Path) -> dict[str, object]:
    return {
        "root": str(paths.root),
        "working": str(paths.working.path),
        "working_source": paths.working.source.value,
        "knowledge": str(paths.knowledge.path),
        "knowledge_source": paths.knowledge.source.value,
        "memory": str(paths.memory.path),
        "memory_source": paths.memory.source.value,
        "learn": str(paths.learn.path),
        "learn_source": paths.learn.source.value,
        "toz": str(paths.toz.path) if paths.toz else None,
        "toz_source": paths.toz.source.value if paths.toz else None,
        "config": str(config),
        "legacy_memory_bank": _legacy_memory_bank(paths),
    }


def help_text(path: str) -> str:
    """Read a committed help snapshot for an app route."""
    parts = path.replace("_", "-").split()
    while parts and parts[0] in {"learn", "knowledge", "setup"}:
        parts = parts[1:]
    key = "_".join(parts).replace("-", "_") or "knowledge"
    help_file = Path(__file__).with_name("help") / f"{key}.txt"
    if not help_file.is_file():
        raise KeyError(f"no knowledge help snapshot for route {path!r}")
    return help_file.read_text(encoding="utf-8")


__all__ = ["help_text", "run"]
