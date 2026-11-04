"""Indexed import target resolution shared by the graph resolver."""

from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from varde_code.parse import language_for_path

from .aux import integer_value, resolve_module

_PACKAGE_FILES = {
    "__init__.py",
    "index.js",
    "index.jsx",
    "index.mjs",
    "index.cjs",
    "index.ts",
    "index.tsx",
    "init.lua",
}
_MAX_SUFFIX = 6
_RUST_STANDARD_CRATES = {
    "alloc",
    "compiler_builtins",
    "core",
    "panic_abort",
    "panic_unwind",
    "proc_macro",
    "std",
    "test",
}


class ImportIndex:
    """Indexes source paths once so each import probes only matching keys."""

    def __init__(self, files: Sequence[str]) -> None:
        self.files = files
        self.file_list = list(files)
        self.paths = [PurePosixPath(path) for path in files]
        self.languages = [language_for_path(str(path)) for path in self.paths]
        self.stems: dict[str, list[int]] = defaultdict(list)
        self.relative: dict[str, list[int]] = defaultdict(list)
        self.suffixes: dict[str, list[int]] = defaultdict(list)
        self.packages: dict[str, list[int]] = defaultdict(list)
        self.modules: dict[str, list[int]] = defaultdict(list)
        self.by_path: dict[str, int] = {}
        self.python_roots: dict[str, set[str]] = defaultdict(set)
        self.rust_module_roots: dict[str, Path] = {}
        self.rust_module_bases: dict[str, Path] = {}
        self.rust_path_attr_cache: dict[str, dict[str, str]] = {}
        self.rust_decl_cache: dict[str, dict[int, int]] = {}
        self.go_modules = _read_go_modules(files)
        self.go_packages: dict[str, list[int]] = defaultdict(list)
        self.rust_roots: list[Path | None] = [
            _cargo_root(path) if lang == "rust" else None
            for path, lang in zip(self.paths, self.languages, strict=False)
        ]
        self.cargo_dependencies = {
            root: _cargo_dependencies(root)
            for root in set(self.rust_roots)
            if root is not None
        }
        self.rust_external_crates = {
            root: _cargo_external_crates(root)
            for root in set(self.rust_roots)
            if root is not None
        }

        for file_id, (path, language) in enumerate(
            zip(self.paths, self.languages, strict=False)
        ):
            normalized_path = _normalize(str(path))
            self.by_path.setdefault(normalized_path, file_id)
            if language is None:
                continue
            if language == "python" and path.name == "__init__.py":
                self.python_roots[path.parent.name].add(_normalize(str(path.parent)))
            self.stems[path.stem].append(file_id)
            self.relative[_without_suffix(path)].append(file_id)
            parts = _without_suffix(path).split("/")
            for start in range(max(0, len(parts) - _MAX_SUFFIX), len(parts)):
                self.suffixes["/".join(parts[start:])].append(file_id)
            if path.name in _PACKAGE_FILES:
                directory = _normalize(str(path.parent))
                components = directory.split("/")
                for start in range(len(components)):
                    self.packages["/".join(components[start:])].append(file_id)
            if language == "go" and not path.name.endswith("_test.go"):
                self.go_packages[_normalize(str(path.parent))].append(file_id)
        rust_root_files = {
            _normalize(str(path.parent))
            for path, language in zip(self.paths, self.languages, strict=False)
            if language == "rust" and path.name in {"lib.rs", "main.rs"}
        }
        for path, language, package_root in zip(
            self.paths, self.languages, self.rust_roots, strict=False
        ):
            if language != "rust":
                continue
            module_root = _rust_target_root(path, package_root, self.by_path)
            if module_root is not None:
                source_key = _normalize(str(path))
                self.rust_module_roots[source_key] = Path(module_root)
                self.rust_module_bases[source_key] = Path(
                    _rust_module_base(path, module_root)
                )
                continue
            for parent in path.parents:
                root = _normalize(str(parent))
                if root in rust_root_files:
                    self.rust_module_roots[_normalize(str(path))] = Path(parent)
                    self.rust_module_bases[_normalize(str(path))] = Path(
                        parent
                        if path.name in {"lib.rs", "main.rs", "mod.rs"}
                        else parent / path.stem
                    )
                    break

    def match(
        self, specifier: str, from_file: int, source_line: int | None = None
    ) -> list[int]:
        if not 0 <= from_file < len(self.files):
            return []
        source = self.paths[from_file]
        language = self.languages[from_file]
        raw = _strip_quotes(specifier).replace("\\", "/").strip()

        if language == "php" and raw.endswith(".php"):
            return []
        if language == "rust" and raw == "mod main" and source.name == "lib.rs":
            return []
        if language == "rust":
            if self._is_external_rust_path(raw, from_file):
                return []
            target = self._match_rust_declaration(raw, from_file, source_line)
            if target is not None:
                return [target]
            target = resolve_module(
                "rust",
                raw,
                self.file_list[from_file],
                self.file_list,
                by_path=self.by_path,
                crate_roots=self.rust_module_roots,
                module_bases=self.rust_module_bases,
            )
            if target is not None and self._rust_package_compatible(
                raw, from_file, target
            ):
                if (
                    raw.startswith("mod ")
                    and source.name == "lib.rs"
                    and self.paths[target].name == "main.rs"
                ):
                    return []
                return [target]
            target = self._match_rust_path_attribute(raw, from_file)
            if target is not None:
                return [target]
            target = self._match_rust_package(raw, from_file)
            if target is not None:
                return [target]
        if language == "python":
            target = resolve_module(
                "python",
                raw,
                self.file_list[from_file],
                self.file_list,
                by_path=self.by_path,
                package_roots=self.python_roots,
            )
            if target is not None:
                return [target]
        if language == "go":
            targets = self._match_go(raw, from_file)
            if targets is not None:
                return targets

        module_targets = self.modules.get(raw, ())
        compatible_modules = [
            target
            for target in module_targets
            if self._compatible(language, self.languages[target])
        ]
        if len(compatible_modules) == 1:
            return compatible_modules

        candidates = self._generic_candidates(raw, source, language)
        compatible = [
            candidate
            for candidate in candidates
            if self._compatible(language, self.languages[candidate])
            and self._rust_package_compatible(raw, from_file, candidate)
        ]
        return compatible[:1] if len(compatible) == 1 else []

    def _generic_candidates(
        self, raw: str, source: PurePosixPath, language: str | None
    ) -> set[int]:
        if language == "php" and raw.endswith(".php"):
            return set()
        if language == "bash" and "BASH_SOURCE" in raw:
            local = self.stems.get("lib", ())
            return set(local)
        if raw.startswith("."):
            if language == "python" and not raw.startswith(("./", "../")):
                dots = len(raw) - len(raw.lstrip("."))
                suffix_spec = raw[dots:]
                if "." in suffix_spec:
                    return set()
                base = source.parent
                for _ in range(max(dots - 1, 0)):
                    base = base.parent
                suffix = suffix_spec.lstrip("/")
                relative = PurePosixPath(_normalize(str(base / suffix)))
            else:
                relative = PurePosixPath(_normalize(str(source.parent / raw)))
            key = _without_suffix(relative)
            matches = set(self.relative.get(key, ())) | set(
                self.packages.get(_normalize(str(relative)), ())
            )
            if matches:
                return matches
            raw = raw.lstrip("./")

        normalized = raw.lstrip("/").replace("::", "/")
        if language == "rust" and normalized.startswith("mod "):
            normalized = normalized[4:]
        if PurePosixPath(normalized).suffix in {
            ".sh",
            ".dart",
            ".php",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
        }:
            normalized = _without_suffix(PurePosixPath(normalized))
        elif "/" not in raw and ("." in raw or ":" in raw):
            normalized = re.sub(r"[.:]+", "/", raw)
        segments = [part for part in normalized.split("/") if part]
        if not segments:
            return set()
        compatible = lambda ids: {
            candidate
            for candidate in ids
            if self._compatible(language, self.languages[candidate])
        }
        for start in range(max(0, len(segments) - _MAX_SUFFIX), len(segments) - 1):
            key = "/".join(segments[start:])
            matches = compatible(self.suffixes.get(key, ()))
            if len(matches) == 1:
                return matches
        for segment in reversed(segments):
            stem_matches = compatible(self.stems.get(segment, ()))
            if stem_matches:
                return stem_matches
        for start in range(len(segments)):
            matches = compatible(self.packages.get("/".join(segments[start:]), ()))
            if matches:
                return matches
        return set()

    def _match_go(self, specifier: str, from_file: int) -> list[int] | None:
        for module_path, root in self.go_modules:
            if specifier == module_path:
                relative = ""
            elif specifier.startswith(module_path + "/"):
                relative = specifier[len(module_path) + 1 :]
            else:
                continue
            target_dir = _normalize(str(PurePosixPath(root) / relative))
            targets = [
                file_id
                for file_id in self.go_packages.get(target_dir, ())
                if file_id != from_file
            ]
            return targets
        return None

    def _rust_package_compatible(
        self, specifier: str, source_id: int, target_id: int
    ) -> bool:
        if self.languages[source_id] != "rust":
            return True
        source_root = self.rust_roots[source_id]
        target_root = self.rust_roots[target_id]
        if source_root is None or target_root is None or source_root == target_root:
            return True
        raw = specifier.strip().lstrip(":")
        root_name = raw.split("::", 1)[0]
        allowed_path_dependency = (
            root_name in self.cargo_dependencies.get(source_root, {})
            and target_root in self.cargo_dependencies[source_root].values()
        )
        if not allowed_path_dependency:
            return False
        manifest = _cargo_manifest(target_root)
        lib = manifest.get("lib", {})
        lib_path = lib.get("path") if isinstance(lib, dict) else None
        lib_path = lib_path or "src/lib.rs"
        return _normalize(str(target_root / lib_path)) in self.by_path

    def _match_rust_package(self, specifier: str, from_file: int) -> int | None:
        source_root = self.rust_roots[from_file]
        if source_root is None:
            return None
        parts = specifier.strip().lstrip(":").split("::")
        if not parts or not parts[0]:
            return None
        manifest = _cargo_manifest(source_root)
        package = manifest.get("package", {})
        lib = manifest.get("lib", {})
        own_names = {
            str(package.get("name", "")).replace("-", "_"),
            str(lib.get("name", "")).replace("-", "_") if isinstance(lib, dict) else "",
        }
        crate_name = parts[0]
        target_root = (
            source_root
            if crate_name in own_names
            else self.cargo_dependencies.get(source_root, {}).get(crate_name)
        )
        if target_root is None:
            try:
                relative_source = self.paths[from_file].relative_to(source_root)
            except ValueError:
                relative_source = PurePosixPath()
            if parts[0] != "common" or relative_source.parts[:2] != (
                "tests",
                "workflow",
            ):
                return None
            dependency_roots = set(
                self.cargo_dependencies.get(source_root, {}).values()
            )
            for module_name in reversed(parts):
                candidates = {
                    file_id
                    for file_id in self.stems.get(module_name, ())
                    if self.rust_roots[file_id] in dependency_roots
                }
                if len(candidates) == 1:
                    return next(iter(candidates))
                if candidates:
                    return None
            return None
        target_manifest = (
            manifest if target_root == source_root else _cargo_manifest(target_root)
        )
        if target_root != source_root and not any(
            _normalize(str(target_root / candidate)) in self.by_path
            for candidate in ("src/lib.rs", "src/main.rs", "lib.rs", "main.rs")
        ):
            return None
        lib = target_manifest.get("lib", {})
        custom_path = lib.get("path") if isinstance(lib, dict) else None
        candidates = [
            target_root / custom_path if custom_path else target_root / "src/lib.rs",
            target_root / "src/main.rs",
            target_root / "lib.rs",
            target_root / "main.rs",
        ]
        crate_file = next(
            (path for path in candidates if _normalize(str(path)) in self.by_path), None
        )
        if crate_file is None:
            return None
        crate_id = self.by_path[_normalize(str(crate_file))]
        if len(parts) == 1:
            return crate_id
        target = resolve_module(
            "rust",
            "crate::" + "::".join(parts[1:]),
            self.file_list[crate_id],
            self.file_list,
            by_path=self.by_path,
            crate_roots=self.rust_module_roots,
            module_bases=self.rust_module_bases,
        )
        return target if target is not None else crate_id

    def _match_rust_path_attribute(self, specifier: str, from_file: int) -> int | None:
        if not specifier.startswith("mod "):
            return None
        source = self.file_list[from_file]
        attributes = self.rust_path_attr_cache.get(source)
        if attributes is None:
            attributes = {}
            try:
                contents = Path(source).read_text()
            except OSError, UnicodeError:
                contents = ""
            for match in re.finditer(
                r'#\[path\s*=\s*"([^"]+)"\]\s*mod\s+([A-Za-z_][\w]*)',
                contents,
            ):
                attributes[match.group(2)] = match.group(1)
            self.rust_path_attr_cache[source] = attributes
        module_name = specifier[4:].split("::", 1)[0].strip()
        path = attributes.get(module_name)
        if path is None:
            return None
        target_path = _normalize(str(Path(source).parent / path))
        return self.by_path.get(target_path)

    def _match_rust_declaration(
        self, specifier: str, from_file: int, source_line: int | None
    ) -> int | None:
        if source_line is None or not specifier.startswith("mod "):
            return None
        source = self.file_list[from_file]
        targets = self.rust_decl_cache.get(source)
        if targets is None:
            targets = _rust_declaration_targets(
                source,
                self.rust_module_bases.get(_normalize(source), Path(source).parent),
                self.by_path,
            )
            self.rust_decl_cache[source] = targets
        return targets.get(source_line)

    def _is_external_rust_path(self, specifier: str, from_file: int) -> bool:
        source_root = self.rust_roots[from_file]
        if source_root is None:
            return False
        first = specifier.strip().lstrip(":").split("::", 1)[0]
        manifest = _cargo_manifest(source_root)
        package = manifest.get("package", {})
        lib = manifest.get("lib", {})
        own = {
            str(package.get("name", "")).replace("-", "_"),
            str(lib.get("name", "")).replace("-", "_") if isinstance(lib, dict) else "",
        }
        return first in _RUST_STANDARD_CRATES or (
            first in self.rust_external_crates.get(source_root, set())
            and first not in own
        )

    @staticmethod
    def _compatible(source: str | None, target: str | None) -> bool:
        return source is None or source == target


def resolve_import_targets(
    entities: Sequence[Mapping[str, object]], files: Sequence[str]
) -> list[tuple[int, int, int | None]]:
    """Return `(source file, import entity, target file)` rows."""
    index = ImportIndex(files)
    for entity in entities:
        kind = entity.get("kind")
        if kind in {1, 2, "class", "interface"} and isinstance(entity.get("name"), str):
            name = str(entity["name"])
            if "." in name:
                index.modules[name].append(integer_value(entity["file_id"]))
    result = []
    for entity_id, entity in enumerate(entities):
        if str(entity.get("kind", "")).lower() != "import" and entity.get("kind") != 9:
            continue
        file_id = integer_value(entity["file_id"])
        start_line = entity.get("start_line")
        targets = index.match(
            str(entity["name"]),
            file_id,
            start_line if isinstance(start_line, int) else None,
        )
        for target in targets or [None]:
            result.append((file_id, entity_id, target))
    return result


def _read_go_modules(files: Sequence[str]) -> list[tuple[str, str]]:
    modules = []
    for value in files:
        path = Path(value)
        if path.name != "go.mod":
            continue
        try:
            contents = path.read_text()
        except OSError:
            continue
        for line in contents.splitlines():
            match = re.match(r'^\s*module\s+("[^"]+"|\S+)', line)
            if match:
                modules.append(
                    (match.group(1).strip('"'), _normalize(str(path.parent)))
                )
                break
    return sorted(modules, key=lambda module: len(module[0]), reverse=True)


def _cargo_root(path: PurePosixPath) -> Path | None:
    for parent in (path.parent, *path.parents):
        if (Path(str(parent)) / "Cargo.toml").is_file():
            return Path(str(parent))
    return None


def _rust_declaration_targets(
    source: str, module_base: Path, by_path: Mapping[str, int]
) -> dict[int, int]:
    try:
        lines = Path(source).read_text().splitlines()
    except OSError, UnicodeError:
        return {}
    targets = {}
    inline: list[tuple[str, int]] = []
    depth = 0
    path_attr = None
    declaration = re.compile(
        r"^\s*(?:(?:pub(?:\([^)]*\))?)\s+)?mod\s+([A-Za-z_]\w*(?:::\w+)*)\s*(;|\{)"
    )
    for line_number, line in enumerate(lines, start=1):
        source_line = line.split("//", 1)[0]
        while inline and depth < inline[-1][1]:
            inline.pop()
        attr = re.search(r'#\[path\s*=\s*"([^"]+)"\]', source_line)
        if attr:
            path_attr = attr.group(1)
        match = declaration.match(source_line)
        if match:
            segments = [*([name for name, _ in inline]), *match.group(1).split("::")]
            if match.group(2) == ";":
                if path_attr:
                    target = _normalize(str(Path(source).parent / path_attr))
                    path_attr = None
                    file_id = by_path.get(target)
                else:
                    directory = module_base.joinpath(*segments[:-1])
                    file_id = by_path.get(
                        _normalize(str(directory / f"{segments[-1]}.rs"))
                    )
                    if file_id is None:
                        file_id = by_path.get(
                            _normalize(str(directory / segments[-1] / "mod.rs"))
                        )
                if file_id is not None:
                    targets[line_number] = file_id
            else:
                path_attr = None
        depth += source_line.count("{") - source_line.count("}")
        if match and match.group(2) == "{":
            inline.append((match.group(1).split("::")[-1], depth))
    return targets


def _cargo_manifest(root: Path) -> dict[str, Any]:
    manifest = root / "Cargo.toml"
    try:
        return tomllib.loads(manifest.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return {}


def _cargo_dependencies(root: Path) -> dict[str, Path]:
    manifest = _cargo_manifest(root)
    workspace_root, workspace = _workspace_manifest(root)
    dependencies: dict[str, Path] = {}
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, value in manifest.get(section, {}).items():
            relative = value.get("path") if isinstance(value, dict) else None
            from_workspace = value is True or (
                isinstance(value, dict) and value.get("workspace") is True
            )
            base = root
            if relative is None and from_workspace:
                shared = (
                    workspace.get("workspace", {}).get("dependencies", {}).get(name)
                )
                relative = shared.get("path") if isinstance(shared, dict) else None
                base = workspace_root
            if relative:
                dependencies[name.replace("-", "_")] = Path(
                    _normalize(str(base / relative))
                )
    return dependencies


def _cargo_external_crates(root: Path) -> set[str]:
    manifest = _cargo_manifest(root)
    _, workspace = _workspace_manifest(root)
    external = set()
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, value in manifest.get(section, {}).items():
            path = value.get("path") if isinstance(value, dict) else None
            uses_workspace = value is True or (
                isinstance(value, dict) and value.get("workspace") is True
            )
            if path is None and uses_workspace:
                shared = (
                    workspace.get("workspace", {}).get("dependencies", {}).get(name)
                )
                path = shared.get("path") if isinstance(shared, dict) else None
            if not path:
                external.add(name.replace("-", "_"))
    return external


def _rust_target_root(
    path: PurePosixPath,
    package_root: Path | None,
    by_path: Mapping[str, int],
) -> Path | None:
    if package_root is None:
        return None
    try:
        relative = path.relative_to(package_root)
    except ValueError:
        return None
    parts = relative.parts
    if parts == ("build.rs",):
        return Path(str(package_root))
    if len(parts) >= 2 and parts[0] == "src":
        if len(parts) >= 3 and parts[1] == "bin":
            return Path(str(package_root / "src/bin"))
        return Path(str(package_root / "src"))
    if len(parts) >= 2 and parts[0] in {"tests", "benches", "examples"}:
        target_dir = package_root / parts[0]
        if len(parts) > 2:
            candidate = target_dir / parts[1]
            if _normalize(str(candidate / "main.rs")) in by_path:
                return Path(str(candidate))
        return Path(str(target_dir))
    return None


def _rust_module_base(path: PurePosixPath, module_root: Path) -> Path:
    target_root = path.parent == PurePosixPath(module_root) and module_root.name in {
        "tests",
        "benches",
        "examples",
        "bin",
    }
    if target_root or path.name in {
        "lib.rs",
        "main.rs",
        "mod.rs",
    }:
        return Path(path.parent)
    return Path(path.parent / path.stem)


def _workspace_manifest(
    root: Path,
) -> tuple[Path, dict[str, Any]]:
    for parent in (root, *root.parents):
        manifest = _cargo_manifest(parent)
        if "workspace" in manifest:
            return Path(str(parent)), manifest
    return Path(str(root)), {}


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _without_suffix(path: PurePosixPath) -> str:
    return _normalize(str(path.with_suffix("")))


def _normalize(path: str) -> str:
    absolute = path.startswith("/")
    parts = []
    for part in path.replace("\\", "/").split("/"):
        if part in {"", "."}:
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    normalized = "/".join(parts)
    return f"/{normalized}" if absolute else normalized
