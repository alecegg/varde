"""Read and validate Markdown friction imports."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from .errors import StoreInvalid, StoreIo
from .store.types import (
    FrictionIncidentProvenance,
    FrictionOccurrence,
    FrictionStatus,
    FrictionStatusChange,
    validate_provenance,
    validate_tag,
)


@dataclass
class FrictionImportEntry:
    id: int | None
    slug: str
    title: str
    source: str
    repo_root: str | None
    status: FrictionStatus
    target: str | None
    created_at: str | None
    occurrences: list[FrictionOccurrence]
    status_changes: list[FrictionStatusChange]
    tags: list[str] = field(default_factory=list)


@dataclass
class FrictionImportFile:
    file: str
    entry: FrictionImportEntry | None = None
    reason: str | None = None

    @classmethod
    def ready(cls, file: str, entry: FrictionImportEntry) -> FrictionImportFile:
        return cls(file, entry=entry)

    @classmethod
    def skipped(cls, file: str, reason: str) -> FrictionImportFile:
        return cls(file, reason=reason)


@dataclass
class FrictionImportSummary:
    total: int = 0
    imported: int = 0
    would_import: int = 0
    skipped: int = 0


def read_import_files(directory: Path, repo_root: Path) -> list[FrictionImportFile]:
    try:
        directory.lstat()
    except OSError as error:
        raise StoreIo("inspect import directory", directory, error) from error
    if directory.is_symlink() or not directory.is_dir():
        raise StoreInvalid(
            f"import source `{directory}` must be a directory, not a symlink"
        )

    try:
        directory = directory.resolve(strict=True)
    except OSError as error:
        raise StoreIo("resolve import directory", directory, error) from error
    normalized_repo_root = normalize_repo_root(repo_root)
    try:
        paths = sorted(
            path for path in directory.iterdir() if path.suffix.lower() == ".md"
        )
    except OSError as error:
        raise StoreIo("read import directory", directory, error) from error

    results: list[FrictionImportFile] = []
    for path in paths:
        file = path.name
        try:
            path.lstat()
        except OSError as error:
            raise StoreIo("inspect import file", path, error) from error
        if path.is_symlink():
            results.append(
                FrictionImportFile.skipped(file, "symbolic links are not imported")
            )
            continue
        if not path.is_file():
            results.append(
                FrictionImportFile.skipped(file, "not a regular Markdown file")
            )
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as stream:
                contents = stream.read()
        except (OSError, UnicodeError) as error:
            results.append(
                FrictionImportFile.skipped(file, f"could not read Markdown: {error}")
            )
            continue
        try:
            entry = parse_markdown(contents, path, normalized_repo_root)
        except ValueError as error:
            results.append(FrictionImportFile.skipped(file, str(error)))
        else:
            results.append(FrictionImportFile.ready(file, entry))
    return results


def parse_markdown(contents: str, path: Path, repo_root: str) -> FrictionImportEntry:
    frontmatter, body = split_frontmatter(contents)
    try:
        mapping = _load_yaml(frontmatter)
    except Exception as error:
        raise ValueError(f"invalid YAML frontmatter: {error}") from error
    if not isinstance(mapping, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    if optional_string(mapping, "format") == "varde-friction-item":
        return parse_structured(mapping)
    return parse_legacy(mapping, body, path, repo_root)


def _load_yaml(frontmatter: str) -> Any:
    import yaml
    from yaml.nodes import MappingNode

    class SerdeYamlLoader(yaml.SafeLoader):
        pass

    SerdeYamlLoader.yaml_implicit_resolvers = copy.deepcopy(
        yaml.SafeLoader.yaml_implicit_resolvers
    )

    # Keep YAML 1.2 core numbers while leaving YAML 1.1 numeric forms as text.
    for first, resolvers in list(SerdeYamlLoader.yaml_implicit_resolvers.items()):
        SerdeYamlLoader.yaml_implicit_resolvers[first] = [
            (tag, regexp)
            for tag, regexp in resolvers
            if tag
            not in {
                "tag:yaml.org,2002:bool",
                "tag:yaml.org,2002:timestamp",
                "tag:yaml.org,2002:int",
                "tag:yaml.org,2002:float",
            }
        ]
    SerdeYamlLoader.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
        list("tTfF"),
    )
    decimal = r"(?:0|[1-9][0-9]*)"
    SerdeYamlLoader.add_implicit_resolver(
        "tag:yaml.org,2002:int",
        re.compile(rf"^[+-]?(?:{decimal}|0[oO][0-7]+)$"),
        list("+-0123456789"),
    )
    SerdeYamlLoader.add_implicit_resolver(
        "tag:yaml.org,2002:float",
        re.compile(
            rf"^[+-]?(?:(?:{decimal}\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|{decimal}[eE][+-]?[0-9]+)$"
        ),
        list("+-0123456789."),
    )

    def construct_mapping(
        self: SerdeYamlLoader, node: MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        mapping: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError:
                continue
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f'duplicate entry with key "{key}"',
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping

    SerdeYamlLoader.construct_mapping = construct_mapping

    def construct_integer(loader: Any, node: Any) -> int:
        value = loader.construct_scalar(node)
        sign = -1 if value.startswith("-") else 1
        unsigned = value.lstrip("+-")
        return sign * (
            int(unsigned, 0) if unsigned.lower().startswith("0o") else int(unsigned, 10)
        )

    SerdeYamlLoader.add_constructor("tag:yaml.org,2002:int", construct_integer)
    return yaml.load(frontmatter, Loader=SerdeYamlLoader)  # noqa: S506 - Loader subclasses SafeLoader with restricted constructors.


def parse_structured(mapping: dict[Any, Any]) -> FrictionImportEntry:
    version = required_i64(mapping, "version")
    if version != 1:
        raise ValueError(f"unsupported friction export version `{version}`")
    item_id = required_positive_id(mapping, "id")
    slug = slugify(required_nonblank(mapping, "slug"))
    title = required_nonblank(mapping, "title")
    source = required_nonblank(mapping, "source")
    repo_root = optional_string(mapping, "repo_root")
    status = parse_status(required_string(mapping, "status"))
    target = optional_string(mapping, "target")
    tags = mapping.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of strings")
    for tag in tags:
        try:
            validate_tag(tag)
        except StoreInvalid as error:
            raise ValueError(error.message) from error
    created_at = required_nonblank(mapping, "created_at")
    occurrences = [
        parse_occurrence(value, item_id) for value in sequence(mapping, "occurrences")
    ]
    status_changes = [
        parse_status_change(value, item_id)
        for value in sequence(mapping, "status_changes")
    ]
    return FrictionImportEntry(
        item_id,
        slug,
        title,
        source,
        repo_root,
        status,
        target,
        created_at,
        occurrences,
        status_changes,
        tags,
    )


def parse_occurrence(value: Any, item_id: int) -> FrictionOccurrence:
    mapping = _mapping(value, "each occurrence must be a YAML mapping")
    occurrence_id = required_positive_id(mapping, "id")
    if required_positive_id(mapping, "item_id") != item_id:
        raise ValueError("occurrence item_id does not match its item")
    return FrictionOccurrence(
        occurrence_id,
        item_id,
        required_nonblank(mapping, "at"),
        required_nonblank(mapping, "cwd"),
        optional_string(mapping, "repo_root"),
        optional_string(mapping, "head_sha"),
        required_nonblank(mapping, "evidence"),
        optional_string(mapping, "cost"),
        optional_provenance(mapping),
    )


def optional_provenance(mapping: dict[Any, Any]) -> FrictionIncidentProvenance | None:
    value = get(mapping, "provenance")
    if value is None:
        return None
    value = _mapping(value, "invalid incident provenance: expected a mapping")
    try:
        provenance = FrictionIncidentProvenance(
            incident_key=_provenance_string(value, "incident_key"),
            identity_version=_provenance_int(value, "identity_version", 0xFFFFFFFF),
            harness=_provenance_string(value, "harness"),
            thread_id=_provenance_string(value, "thread_id"),
            incident_kind=_provenance_string(value, "incident_kind"),
            witness_id=_provenance_optional_string(value, "witness_id"),
            source_id=_provenance_string(value, "source_id"),
            record_index=_provenance_int(value, "record_index", (1 << 64) - 1),
            byte_start=_provenance_int(value, "byte_start", (1 << 64) - 1),
            byte_end=_provenance_int(value, "byte_end", (1 << 64) - 1),
            record_digest=_provenance_string(value, "record_digest"),
            payload_digest=_provenance_string(value, "payload_digest"),
        )
        validate_provenance(provenance)
    except (KeyError, TypeError, ValueError, StoreInvalid) as error:
        raise ValueError(f"invalid incident provenance: {error}") from error
    return provenance


def parse_status_change(value: Any, item_id: int) -> FrictionStatusChange:
    mapping = _mapping(value, "each status change must be a YAML mapping")
    change_id = required_positive_id(mapping, "id")
    if required_positive_id(mapping, "item_id") != item_id:
        raise ValueError("status change item_id does not match its item")
    return FrictionStatusChange(
        change_id,
        item_id,
        required_nonblank(mapping, "at"),
        parse_status(required_string(mapping, "from_status")).as_str(),
        parse_status(required_string(mapping, "to_status")).as_str(),
        required_nonblank(mapping, "reason"),
    )


def parse_legacy(
    mapping: dict[Any, Any], body: str, path: Path, repo_root: str
) -> FrictionImportEntry:
    item_type = optional_string(mapping, "type")
    if item_type not in {"friction", "friction-item"}:
        raise ValueError("missing or unsupported friction type")
    status_value = optional_string(mapping, "status")
    status = (
        parse_status(status_value) if status_value is not None else FrictionStatus.OPEN
    )
    source = next(
        (
            value
            for key in ("source", "skill", "tool")
            if (value := optional_string(mapping, key)) is not None
        ),
        "legacy-import",
    )
    if not source.strip():
        raise ValueError("source must not be blank")
    title = optional_string(mapping, "title")
    if title is None:
        title = first_heading(body) or humanize_filename(path)
    elif not title.strip():
        raise ValueError("title must not be blank")
    created_at = first_legacy_string(mapping, ("created_at", "created", "date"))
    cwd = optional_string(mapping, "cwd")
    if cwd is None:
        cwd = repo_root
    if not cwd.strip():
        raise ValueError("`cwd` must not be blank")
    head_sha = optional_scalar_text(mapping, "head_sha")
    evidence = body.strip()
    if not evidence:
        raise ValueError("Markdown body must contain occurrence evidence")
    slug = slugify(path.stem)
    return FrictionImportEntry(
        None,
        slug,
        title,
        source,
        repo_root,
        status,
        optional_string(mapping, "target"),
        created_at if created_at and created_at.strip() else None,
        [
            FrictionOccurrence(
                0,
                0,
                created_at or _now_timestamp(),
                cwd,
                repo_root,
                head_sha,
                evidence,
                optional_scalar_text(mapping, "cost"),
            )
        ],
        [],
    )


def _now_timestamp() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def split_frontmatter(contents: str) -> tuple[str, str]:
    lines = contents.splitlines(keepends=True)
    if not lines:
        raise ValueError("missing YAML frontmatter")
    if lines[0].rstrip("\r\n") != "---":
        raise ValueError("missing YAML frontmatter opening delimiter")
    offset = len(lines[0])
    for line in lines[1:]:
        if line.rstrip("\r\n") == "---":
            yaml_start = len(lines[0])
            return contents[yaml_start:offset], contents[offset + len(line) :].lstrip(
                "\r\n"
            )
        offset += len(line)
    raise ValueError("missing YAML frontmatter closing delimiter")


def sequence(mapping: dict[Any, Any], key: str) -> list[Any]:
    value = get(mapping, key)
    if value is None:
        raise ValueError(f"missing `{key}` collection")
    if not isinstance(value, list):
        raise ValueError(f"`{key}` must be a YAML sequence")
    return value


def get(mapping: dict[Any, Any], key: str) -> Any:
    return mapping.get(key)


def required_string(mapping: dict[Any, Any], key: str) -> str:
    value = get(mapping, key)
    if not isinstance(value, str):
        raise ValueError(f"missing or invalid `{key}` string")
    return value


def required_nonblank(mapping: dict[Any, Any], key: str) -> str:
    value = required_string(mapping, key)
    if not value.strip():
        raise ValueError(f"`{key}` must not be blank")
    return value


def required_i64(mapping: dict[Any, Any], key: str) -> int:
    value = get(mapping, key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not -(1 << 63) <= value < (1 << 63)
    ):
        raise ValueError(f"missing or invalid `{key}` integer")
    return value


def required_positive_id(mapping: dict[Any, Any], key: str) -> int:
    value = required_i64(mapping, key)
    if value <= 0:
        raise ValueError(f"`{key}` must be a positive integer")
    return value


def optional_string(mapping: dict[Any, Any], key: str) -> str | None:
    value = get(mapping, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{key}` must be a string or null")
    return value


def optional_scalar_text(mapping: dict[Any, Any], key: str) -> str | None:
    value = get(mapping, key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ValueError(f"`{key}` must be a scalar string or number")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    raise ValueError(f"`{key}` must be a scalar string or number")


def first_legacy_string(mapping: dict[Any, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = optional_string(mapping, key)
        if value is not None:
            return value
    return None


def parse_status(value: str) -> FrictionStatus:
    status = FrictionStatus.parse(value)
    if status is None:
        raise ValueError(f"invalid friction status `{value}`")
    return status


def first_heading(body: str) -> str | None:
    for line in body.splitlines():
        heading = line.strip()
        if heading.startswith("# ") and heading[2:].strip():
            return heading[2:].strip()
    return None


def humanize_filename(path: Path) -> str:
    parts = (part for part in re.split(r"[-_]", path.stem) if part)
    return " ".join(
        (part[0].upper() if part[0].isascii() else part[0]) + part[1:] for part in parts
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not slug:
        return "friction"
    if slug.isascii() and slug.isdigit():
        return f"friction-{slug}"
    return slug


def normalize_repo_root(path: Path) -> str:
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        return str(absolute.resolve(strict=True))
    except OSError:
        return str(absolute)


def _mapping(value: Any, reason: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ValueError(reason)
    return value


def _provenance_string(mapping: dict[Any, Any], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise TypeError(f"{key}: invalid type: expected a string")
    return value


def _provenance_optional_string(mapping: dict[Any, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key}: invalid type: expected a string or null")
    return value


def _provenance_int(mapping: dict[Any, Any], key: str, maximum: int) -> int:
    value = mapping[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise TypeError(f"{key}: invalid type: expected an unsigned integer")
    return value
