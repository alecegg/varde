"""File-canonical Markdown plan reader."""

import os
from dataclasses import replace
from pathlib import Path

from varde_core.frontmatter import FrontmatterError, parse
from varde_data.backends.files.plans_index import PlansIndex
from varde_data.backends.files.plans_write import FilePlansWriter
from varde_data.errors import Conflict, NotFound
from varde_data.locking import remove_stale_temps
from varde_data.records.plans import PlanRecord, ReadResult, TaskRecord
from varde_data.version import Version

KNOWN = {"id", "type", "artifact_type", "status", "title", "owner", "assigned_to"}


class FilesPlans(FilePlansWriter):
    def __init__(self, working_dir: Path) -> None:
        self.root = working_dir / "plans"
        self._cleaned: set[Path] = set()
        self._index = PlansIndex(self.root)

    def _cleanup(self, directories: tuple[Path, ...]) -> None:
        pending = set(directories) - self._cleaned
        for directory in sorted(pending):
            remove_stale_temps(directory, 86400)
        self._cleaned.update(pending)

    def list(
        self, *, include_archived: bool = False, include_tasks: bool = True
    ) -> ReadResult:
        paths, skipped = self._plan_paths(include_archived)
        self._cleanup(tuple(sorted({path.parent for path in paths})))
        records = []
        for path in paths:
            try:
                record = self._read_plan(path, self._is_archived(path))
            except OSError, FrontmatterError, UnicodeError:
                skipped += 1
                continue
            if record is None:
                skipped += 1
                continue
            if record.artifact_type == "plan":
                record = self._with_review(record)
                if include_tasks:
                    record = self._with_tasks(record)
            records.append(record)
        return ReadResult(tuple(records), skipped)

    def get(self, plan_ref: str, *, include_archived: bool = False) -> PlanRecord:
        paths, _ = self._plan_paths(include_archived)
        id_matches = []
        for path in paths:
            try:
                head = _read_frontmatter(self._index.read(path))
            except OSError, UnicodeError:
                continue
            if _simple_id_mismatch(head, plan_ref):
                continue
            fields = _resolvable_head_fields(head)
            if fields is not None and fields.get("id") == plan_ref:
                id_matches.append(path)
        winner = _unique_head_match(plan_ref, id_matches)
        if winner is None:
            directory_matches = [path for path in paths if path.parent.name == plan_ref]
            winner = _unique_parsed_head_match(plan_ref, directory_matches, self._index)
        if winner is None:
            suffix_matches = [
                path for path in paths if _date_suffix(path.parent.name, plan_ref)
            ]
            winner = _unique_parsed_head_match(plan_ref, suffix_matches, self._index)
        if winner is None:
            raise NotFound(f"plan {plan_ref!r} not found")
        self._cleanup((winner.parent,))
        try:
            record = self._read_plan(winner, self._is_archived(winner))
        except OSError, FrontmatterError, UnicodeError:
            record = None
        if record is None:
            raise NotFound(f"plan {plan_ref!r} not found")
        if record.artifact_type == "plan":
            record = self._with_review(record)
            record = self._with_tasks(record)
        return record

    def get_by_path(self, path: str) -> PlanRecord:
        """Parse a single plan or task document at a caller-resolved path."""
        source = Path(os.path.abspath(path))
        root = Path(os.path.abspath(self.root))
        try:
            source.relative_to(root)
            source.resolve(strict=True).relative_to(root.resolve())
            archived = "archive" in source.relative_to(root).parts[:-1]
        except OSError, RuntimeError, ValueError:
            raise NotFound(f"plan file {path!r} not found") from None
        self._cleanup((source.parent,))
        try:
            record = self._read_plan(source, archived)
        except OSError, FrontmatterError, UnicodeError:
            record = None
        if record is None:
            raise NotFound(f"plan file {path!r} not found")
        if record.artifact_type == "plan":
            record = self._with_review(record)
            record = self._with_tasks(record)
        return record

    def owner_lookup(
        self, owner: str, *, include_archived: bool = False
    ) -> tuple[PlanRecord, ...]:
        paths, _ = self._plan_paths(include_archived)
        records = []
        for path in paths:
            if path.name != "plan.md":
                continue
            try:
                record = self._read_plan(
                    path,
                    self._is_archived(path),
                )
            except OSError, FrontmatterError, UnicodeError:
                continue
            if (
                record is not None
                and record.artifact_type == "plan"
                and record.fields.get("owner") == owner
            ):
                records.append(record)
        return tuple(records)

    def version(self) -> Version:
        with self._index.lock:
            return self._index.version()

    def _plan_paths(self, include_archived: bool) -> tuple[list[Path], int]:
        if not self.root.exists():
            return [], 0
        with self._index.lock:
            return self._collect_plan_paths(self.root, include_archived)

    def _collect_plan_paths(
        self,
        directory: Path,
        include_archived: bool,
        ancestors: frozenset[tuple[int, int]] = frozenset(),
    ) -> tuple[list[Path], int]:
        try:
            child_paths = self._index.paths(directory)
            if child_paths is None:
                return [], 1
            entries = child_paths
        except OSError:
            return [], 1
        identity = self._index.directory_id(directory)
        if identity is not None and identity in ancestors:
            return [], 0
        if identity is not None:
            ancestors = ancestors | {identity}
        paths = []
        skipped = 0
        has_plan = any(
            path.name == "plan.md" and (is_dir or is_file)
            for path, is_dir, is_file, _ in entries
        )
        for path, is_dir, is_file, is_symlink in entries:
            entry_name = path.name
            try:
                if is_dir:
                    if not include_archived and path.name == "archive":
                        continue
                    if path.name == "tasks" and has_plan:
                        continue
                    child_paths, child_skipped = self._collect_plan_paths(
                        path, include_archived, ancestors
                    )
                    paths.extend(child_paths)
                    skipped += child_skipped
                elif (
                    entry_name in {"plan.md", "task.md"}
                    and (is_file or is_symlink)
                    and (
                        entry_name == "plan.md"
                        or not (path.parent / "plan.md").exists()
                    )
                ):
                    paths.append(path)
            except OSError:
                skipped += 1
        return paths, skipped

    def _is_archived(self, path: Path) -> bool:
        return "archive" in path.relative_to(self.root).parts[:-1]

    def _read_plan(self, path: Path, archived: bool) -> PlanRecord | None:
        with self._index.lock:
            raw, fields = self._index.fields(path, parse, normalize_newlines=True)
        kind = _string(fields, "artifact_type") or _string(fields, "type") or "plan"
        if kind not in {"plan", "task"}:
            return None
        stat = path.stat()
        identifier = _string(fields, "id")
        if identifier is None:
            identifier = (
                path.parent.name if path.name in {"plan.md", "task.md"} else path.stem
            )
        extra = {key: value for key, value in fields.items() if key not in KNOWN}
        return PlanRecord(
            identifier,
            fields,
            raw,
            stat.st_mtime,
            str(path),
            archived=archived,
            artifact_type=kind,
            extra=extra,
        )

    def _with_review(self, plan: PlanRecord) -> PlanRecord:
        return replace(
            plan,
            review_verdict=_review_verdict(
                Path(plan.path).parent / "review.md", self._index
            ),
        )

    def _with_tasks(self, plan: PlanRecord) -> PlanRecord:
        folder = Path(plan.path).parent / "tasks"
        if not folder.is_dir():
            return plan
        records: list[TaskRecord] = []
        skipped = 0
        with self._index.lock:
            entries = self._index.paths(folder)
        if entries is None:
            return replace(plan, skipped_tasks=1)
        for path, _, is_file, is_symlink in entries:
            if path.suffix != ".md" or not (is_file or is_symlink):
                continue
            try:
                record = _task_record(path, self._index)
                if record is None:
                    skipped += 1
                    continue
                records.append(record)
            except OSError, FrontmatterError, UnicodeError:
                skipped += 1
        return replace(plan, tasks=tuple(records), skipped_tasks=skipped)


def _review_verdict(path: Path, index: PlansIndex) -> str | None:
    try:
        with index.lock:
            _, fields = index.fields(path, parse)
    except OSError, FrontmatterError, UnicodeError:
        return None
    verdict = fields.get("verdict")
    return verdict if isinstance(verdict, str) else None


def _task_record(path: Path, index: PlansIndex) -> TaskRecord | None:
    with index.lock:
        raw, fields = index.fields(path, parse)
    kind = _string(fields, "artifact_type") or _string(fields, "type") or "plan"
    if kind != "task":
        return None
    stat = path.stat()
    identifier = _string(fields, "id") or path.stem
    extra = {key: value for key, value in fields.items() if key not in KNOWN}
    return TaskRecord(identifier, fields, raw, stat.st_mtime, str(path), extra)


def _string(fields: dict[str, object], key: str) -> str | None:
    value = fields.get(key)
    return value if isinstance(value, str) and value else None


def _read_frontmatter(source: bytes) -> bytes:
    """Read only the YAML header, stopping at its closing delimiter."""
    lines = []
    for line_number, line in enumerate(source.splitlines(keepends=True)):
        lines.append(line)
        if line_number and line.rstrip(b"\r\n") == b"---":
            return b"".join(lines)
    return b"".join(lines)


def _simple_id_mismatch(head: bytes, plan_ref: str) -> bool:
    """Avoid YAML parsing when a plain top-level id cannot match the ref."""
    lines = head.splitlines()
    id_lines = [index for index, line in enumerate(lines) if line.startswith(b"id:")]
    if len(id_lines) != 1:
        return False
    id_line = id_lines[0]
    for following in lines[id_line + 1 :]:
        if following.strip(b" \t"):
            if following.startswith((b" ", b"\t")):
                return False
            break
    try:
        value = lines[id_line][3:].decode("utf-8").strip(" \t\r\n")
    except UnicodeDecodeError:
        return False
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote = value[0]
        value = value[1:-1]
        if quote in value:
            return False
    elif '"' in value or "'" in value:
        return False
    if any(character in value for character in "&*!|>{[\\#"):
        return False
    return value != plan_ref


def _resolvable_head_fields(head: bytes) -> dict[str, object] | None:
    try:
        fields, _ = parse(head)
    except FrontmatterError, UnicodeError:
        return None
    kind = _string(fields, "artifact_type") or _string(fields, "type") or "plan"
    return fields if kind in {"plan", "task"} else None


def _unique_parsed_head_match(
    plan_ref: str, paths: list[Path], index: PlansIndex
) -> Path | None:
    matches = []
    for path in paths:
        try:
            head = _read_frontmatter(index.read(path))
        except OSError, UnicodeError:
            continue
        if _resolvable_head_fields(head) is not None:
            matches.append(path)
    return _unique_head_match(plan_ref, matches)


def _unique_head_match(plan_ref: str, paths: list[Path]) -> Path | None:
    if len(paths) > 1:
        raise Conflict(f"plan reference {plan_ref!r} is ambiguous")
    return paths[0] if paths else None


def _date_suffix(dirname: str, plan_ref: str) -> bool:
    return dirname.endswith(f"-{plan_ref}") and len(dirname) > len(plan_ref) + 1
