"""Profile loading and glob matching for capture previews."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

from .config import varde_config_dir


def _raise_invalid_test(message: str) -> NoReturn:
    raise ValueError(message)


class Scope(StrEnum):
    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"


@dataclass
class Diagnostic:
    profile_id: str | None
    file: str
    reason: str


@dataclass
class ProfileTest:
    name: str
    input: str
    expect_records: Any = None
    expect_preview_contains: list[str] = field(default_factory=list)


@dataclass
class Profile:
    id: str
    scope: Scope
    file: Path
    match_kind: str | None = None
    match_pattern: re.Pattern[str] | None = None
    sections_kind: str | None = None
    sections_pattern: re.Pattern[str] | None = None
    jsonl_key: str | None = None
    merge_small: bool = True
    preview_kind: str | None = None
    items_per_section: int | None = None
    item: re.Pattern[str] | None = None
    script: str | None = None
    tests: list[ProfileTest] = field(default_factory=list)

    def matches(self, source: str, is_command: bool = False) -> bool:
        return (
            self.match_pattern is not None
            and (self.match_kind != "command" or is_command)
            and self.match_pattern.search(source) is not None
        )


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        elif ch == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                raise ValueError(f"unterminated `[` in glob {pattern!r}")
            content = pattern[i + 1 : end]
            if not content:
                raise ValueError(f"bad glob {pattern!r}")
            if content.startswith("!"):
                content = "^" + content[1:]
            out.append("[" + content + "]")
            i = end
        else:
            out.append(re.escape(ch))
        i += 1
    out.append("$")
    try:
        return re.compile("".join(out))
    except re.error as exc:
        raise ValueError(f"bad glob {pattern!r}: {exc}") from exc


def _builtin_path() -> Path:
    return Path(__file__).with_name("builtin_profiles.toml")


def user_profiles_path() -> Path:
    return varde_config_dir() / "toz" / "profiles.toml"


def project_profiles_path(root: Path) -> Path:
    return root / ".varde" / "toz-profiles.toml"


def load_file(path: Path) -> tuple[list[Profile], list[Diagnostic]]:
    return _load_paths(None, None, Path("."), direct=path)


def load_profiles(project_root: Path) -> tuple[list[Profile], list[Diagnostic]]:
    return _load_paths(
        user_profiles_path(), project_profiles_path(project_root), project_root
    )


def _load_paths(
    user: Path | None, project: Path | None, root: Path, direct: Path | None = None
):
    profiles: dict[str, Profile] = {}
    diagnostics: list[Diagnostic] = []
    builtin = _builtin_path()
    _load_scope(
        builtin.read_text(), Scope.BUILTIN, builtin, None, profiles, diagnostics
    )
    trusted: list[str] = []
    if direct is not None:
        try:
            _load_scope(
                direct.read_text(), Scope.USER, direct, None, profiles, diagnostics
            )
        except OSError as exc:
            diagnostics.append(
                Diagnostic(None, str(direct), f"cannot read file: {exc}")
            )
    else:
        if user and user.exists():
            try:
                raw = tomllib.loads(user.read_text())
                trusted = [
                    str(item)
                    for item in raw.get("trusted_projects", [])
                    if isinstance(item, str)
                ]
            except OSError, tomllib.TOMLDecodeError:
                pass
            try:
                _load_scope(
                    user.read_text(), Scope.USER, user, None, profiles, diagnostics
                )
            except OSError as exc:
                diagnostics.append(
                    Diagnostic(None, str(user), f"cannot read file: {exc}")
                )
        if project and project.exists():
            is_trusted = any(_same_path(Path(item), root) for item in trusted)
            _load_scope(
                project.read_text(),
                Scope.PROJECT,
                project,
                is_trusted,
                profiles,
                diagnostics,
            )
    return [profiles[key] for key in sorted(profiles)], diagnostics


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def _load_scope(
    text: str,
    scope: Scope,
    path: Path,
    trusted: bool | None,
    profiles: dict[str, Profile],
    diagnostics: list[Diagnostic],
) -> None:
    try:
        root = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        diagnostics.append(Diagnostic(None, str(path), f"invalid TOML: {exc}"))
        return
    entries = root.get("profile", [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        try:
            profile = _parse_entry(entry, scope, path, diagnostics)
            if profile is None:
                continue
            if scope is Scope.PROJECT and profile.script is not None and not trusted:
                profile.script = None
                diagnostics.append(
                    Diagnostic(
                        profile.id,
                        str(path),
                        "script dropped: project is not listed in trusted_projects",
                    )
                )
            profiles[profile.id] = profile
        except (ValueError, TypeError) as exc:
            pid = (
                entry.get("id")
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
                else None
            )
            diagnostics.append(Diagnostic(pid, str(path), str(exc)))


def _parse_entry(
    entry: object, scope: Scope, path: Path, diagnostics: list[Diagnostic]
) -> Profile | None:
    if not isinstance(entry, dict):
        raise ValueError("profile entry is not a table")
    pid = entry.get("id")
    if not isinstance(pid, str) or not pid:
        raise ValueError("missing or empty `id`")
    profile = Profile(pid, scope, path)
    match = entry.get("match")
    if match is not None:
        if not isinstance(match, dict):
            raise ValueError("`match` must be a table")
        chosen = [
            (key, match.get(key))
            for key in ("command", "source")
            if isinstance(match.get(key), str)
        ]
        if len(chosen) != 1:
            raise ValueError("`match` must set exactly one of `command` or `source`")
        profile.match_kind, pattern = chosen[0]
        if not isinstance(pattern, str):
            raise ValueError("`match` pattern must be a string")
        profile.match_pattern = glob_to_regex(pattern)
    sections = entry.get("sections")
    if sections is not None:
        if not isinstance(sections, dict):
            raise ValueError("`sections` must be a table")
        chosen = [
            (key, sections.get(key))
            for key in ("heading", "start", "jsonl_key")
            if isinstance(sections.get(key), str)
        ]
        if len(chosen) != 1:
            raise ValueError(
                "`sections` must set exactly one of `heading`, `start`, or `jsonl_key`"
            )
        profile.sections_kind, value = chosen[0]
        if not isinstance(value, str):
            raise ValueError("`sections` pattern must be a string")
        profile.jsonl_key = value if profile.sections_kind == "jsonl_key" else None
        if profile.jsonl_key is None:
            try:
                profile.sections_pattern = re.compile(value)
            except re.error as exc:
                raise ValueError(
                    f"bad `sections.{profile.sections_kind}` regex: {exc}"
                ) from exc
    if not isinstance(entry.get("merge_small", True), bool):
        raise ValueError("merge_small must be a bool")
    profile.merge_small = entry.get("merge_small", True)
    preview = entry.get("preview")
    if preview is not None:
        if not isinstance(preview, dict):
            raise ValueError("`preview` must be a table")
        kind = preview.get("kind")
        if kind not in ("toc", "head"):
            raise ValueError(f'`preview.kind` must be "toc" or "head", got {kind!r}')
        profile.preview_kind = kind
        count = preview.get("items_per_section")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise ValueError(
                "`preview.items_per_section` must be a non-negative integer"
            )
        profile.items_per_section = count
        if "item" in preview:
            if not isinstance(preview["item"], str):
                raise ValueError("`preview.item` must be a string")
            try:
                profile.item = re.compile(preview["item"])
            except re.error as exc:
                raise ValueError(f"bad `preview.item` regex: {exc}") from exc
    script = entry.get("script")
    if script is not None and not isinstance(script, str):
        raise ValueError("script must be a string")
    profile.script = script
    test_entries = entry.get("test", [])
    for item in test_entries if isinstance(test_entries, list) else []:
        try:
            if not isinstance(item, dict):
                _raise_invalid_test("profile.test entry is not a table")
            if not isinstance(item.get("name"), str):
                _raise_invalid_test("profile.test entry missing string `name`")
            if not isinstance(item.get("input"), str):
                _raise_invalid_test(
                    f"profile.test `{item['name']}` missing string `input`"
                )
            expected = item.get("expect_preview_contains", [])
            expected = (
                [value for value in expected if isinstance(value, str)]
                if isinstance(expected, list)
                else []
            )
            profile.tests.append(
                ProfileTest(
                    item["name"], item["input"], item.get("expect_records"), expected
                )
            )
        except (ValueError, TypeError) as exc:
            diagnostics.append(Diagnostic(pid, str(path), str(exc)))
    return profile


def find_match(
    profiles: list[Profile], source: str, is_command: bool = False
) -> Profile | None:
    rank = {Scope.PROJECT: 0, Scope.USER: 1, Scope.BUILTIN: 2}
    return next(
        (
            p
            for p in sorted(profiles, key=lambda item: rank[item.scope])
            if p.matches(source, is_command)
        ),
        None,
    )
