"""C# and Swift dependency facts based on project and target ownership."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .types import IMPORT_KIND, Fact, FactInput, FileRow, ImportRow


@dataclass
class Line:
    code: str
    guarded: bool


def facts(input: FactInput) -> list[Fact]:
    imports: dict[int, list[ImportRow]] = {}
    for imp in input.imports:
        if not imp.type_only:
            imports.setdefault(imp.file_id, []).append(imp)
    return (
        csharp_facts(input.files, imports)
        + swift_facts(input.files, imports)
        + xcode_facts(input.files, imports)
    )


def source_lines(text: str) -> list[Line]:
    result = []
    in_block = False
    depth = 0
    for raw in text.splitlines():
        out = []
        i = 0
        while i < len(raw):
            if in_block:
                end = raw.find("*/", i)
                if end < 0:
                    break
                i = end + 2
                in_block = False
            else:
                start = raw.find("/*", i)
                if start < 0:
                    out.append(raw[i:])
                    break
                out.append(raw[i:start])
                i = start + 2
                in_block = True
        code = "".join(out)
        code = code.split("//", 1)[0]
        stripped = code.strip()
        if stripped.startswith("#endif"):
            depth = max(0, depth - 1)
        result.append(Line(code, depth > 0))
        if stripped.startswith("#if"):
            depth += 1
    return result


def extension(file: FileRow) -> str | None:
    return Path(file.relative).suffix.removeprefix(".") or None


def candidate(file: FileRow, wanted: str) -> bool:
    return not file.is_test and not file.is_tooling and extension(file) == wanted


def identifier_path(name: str) -> bool:
    return bool(name) and all(
        part
        and (part[0].isalpha() or part[0] == "_")
        and all(c.isalnum() or c == "_" for c in part)
        for part in name.split(".")
    )


def fact(
    source: FileRow, imp: ImportRow, source_unit: str, target: tuple[FileRow, str]
) -> Fact:
    return Fact(
        source.id,
        source_unit,
        target[0].id,
        target[1],
        IMPORT_KIND,
        "certified",
        imp.id,
        imp.specifier,
    )


def read_source(file: FileRow) -> str | None:
    try:
        return file.physical.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


def project_dir(file: FileRow, cache: dict[Path, bool]) -> str | None:
    relative = Path(file.relative).parent
    physical = file.physical.parent
    while True:
        if physical is None:
            return None
        if physical not in cache:
            try:
                cache[physical] = any(p.suffix == ".csproj" for p in physical.iterdir())
            except FileNotFoundError:
                cache[physical] = False
            except OSError as exc:
                raise OSError(f"read project directory {physical}: {exc}") from exc
        if cache[physical]:
            value = relative.as_posix()
            return value if value != "." else "."
        if relative == Path(".") or relative.parent == relative:
            return None
        relative = relative.parent
        physical = physical.parent


def declared_namespaces(lines: list[Line], unit: str, opaque: set[str]) -> list[str]:
    found = []
    for line in lines:
        rest = line.code.lstrip().removeprefix("namespace ")
        if rest == line.code.lstrip() or not line.code.lstrip().startswith(
            "namespace "
        ):
            continue
        name = rest.strip().rstrip("{").rstrip(";").strip()
        if not identifier_path(name):
            continue
        if line.code[:1].isspace():
            opaque.add(unit)
        else:
            found.append(name)
    return found


def plain_usings(lines: list[Line]) -> set[str]:
    result = set()
    for line in lines:
        if line.guarded:
            continue
        value = line.code.strip()
        if value.startswith("using ") and value.endswith(";"):
            name = value[6:-1].strip()
            if identifier_path(name):
                result.add(name)
    return result


def csharp_facts(files, imports_by_file) -> list[Fact]:
    cache: dict[Path, bool] = {}
    declared: dict[str, dict[str, FileRow]] = {}
    opaque: set[str] = set()
    sources = []
    for file in files:
        if not candidate(file, "cs"):
            continue
        unit = project_dir(file, cache)
        text = read_source(file)
        if unit is None or text is None:
            continue
        lines = source_lines(text)
        for namespace in declared_namespaces(lines, unit, opaque):
            current = declared.setdefault(namespace, {}).get(unit)
            if current is None or file.relative < current.relative:
                declared[namespace][unit] = file
        sources.append((file, unit, plain_usings(lines)))
    output = []
    for source, unit, usings in sources:
        for imp in imports_by_file.get(source.id, []):
            namespace = imp.specifier.replace("/", ".")
            targets = declared.get(namespace)
            if namespace not in usings or not targets or len(targets) != 1:
                continue
            target_unit, target = next(iter(targets.items()))
            if target_unit == unit or target_unit in opaque or unit in opaque:
                continue
            output.append(fact(source, imp, unit, (target, target_unit)))
    return output


@dataclass
class SwiftTarget:
    module: str
    unit: str
    remote_packages: bool


def package_manifest(
    file: FileRow,
    sources_index: int,
    components: list[str],
    cache: dict[Path, str | None],
):
    package = file.physical
    for _ in range(len(components) - sources_index):
        package = package.parent
    if package not in cache:
        try:
            cache[package] = (package / "Package.swift").read_text(
                encoding="utf-8", errors="replace"
            )
        except FileNotFoundError:
            cache[package] = None
    return package, cache[package]


def swift_target(
    file: FileRow, manifests: dict[Path, str | None]
) -> SwiftTarget | None:
    parts = file.relative.split("/")
    indices = [i for i in range(max(0, len(parts) - 2)) if parts[i] == "Sources"]
    if not indices:
        return None
    index = indices[-1]
    _, manifest = package_manifest(file, index, parts, manifests)
    module = parts[index + 1]
    if manifest is None or f'"{module}"' not in manifest:
        return None
    return SwiftTarget(
        module,
        "/".join(parts[: index + 2]),
        ".package(url:" in manifest or ".package(name:" in manifest,
    )


def plain_swift_imports(lines: list[Line]) -> set[str]:
    result = set()
    for line in lines:
        if line.guarded:
            continue
        tokens = line.code.split()
        if len(tokens) < 2 or tokens[0] != "import":
            continue
        path = tokens[-1]
        if identifier_path(path):
            result.add(path.replace(".", "/"))
    return result


def package_of(unit: str) -> Path | None:
    path = Path(unit).parent.parent
    return None if path == Path(".") else path


def swift_facts(files, imports_by_file) -> list[Fact]:
    manifests: dict[Path, str | None] = {}
    sources = []
    by_module: dict[str, dict[str, FileRow]] = {}
    targets = {}
    for file in files:
        if not candidate(file, "swift"):
            continue
        target = swift_target(file, manifests)
        if target is None:
            continue
        targets[file.id] = target
        current = by_module.setdefault(target.module, {}).get(target.unit)
        if current is None or file.relative < current.relative:
            by_module[target.module][target.unit] = file
        sources.append(file)
    output = []
    for file in sources:
        target = targets[file.id]
        imports = imports_by_file.get(file.id, [])
        text = read_source(file)
        if not imports or text is None:
            continue
        plain = plain_swift_imports(source_lines(text))
        for imp in imports:
            module = imp.specifier.split("/", 1)[0]
            if imp.specifier not in plain or module == target.module:
                continue
            units = by_module.get(module, {})
            if len(units) != 1:
                continue
            unit, target_file = next(iter(units.items()))
            if target.remote_packages and package_of(unit) != package_of(target.unit):
                continue
            output.append(fact(file, imp, target.unit, (target_file, unit)))
    return output


def xcode_facts(files, imports_by_file) -> list[Fact]:
    """Resolve imports against Xcode project target source directories."""
    root = repository_root(files)
    if root is None:
        return []
    projects = set()
    for file in files:
        if not candidate(file, "swift"):
            continue
        for directory in file.physical.parents:
            if not directory.is_relative_to(root):
                break
            try:
                project = next(
                    (
                        entry
                        for entry in directory.iterdir()
                        if entry.suffix == ".xcodeproj" and entry.is_dir()
                    ),
                    None,
                )
            except FileNotFoundError:
                project = None
            except OSError as exc:
                raise OSError(f"read {directory}: {exc}") from exc
            if project is not None:
                projects.add(project)
                break
            if directory == root:
                break
    by_relative = {file.relative: file for file in files}
    targets = []
    for project in sorted(projects):
        pbx = project / "project.pbxproj"
        try:
            text = pbx.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise OSError(f"read {pbx}: {exc}") from exc
        except UnicodeError as exc:
            raise ValueError(f"read {pbx}: stream did not contain valid UTF-8") from exc
        targets.extend(pbx_swift_targets(text, project.parent, root, by_relative))
    if not targets:
        return []
    module_counts: dict[str, int] = {}
    unit_counts: dict[str, int] = {}
    file_counts: dict[int, int] = {}
    for target in targets:
        module_counts[target[0]] = module_counts.get(target[0], 0) + 1
        unit_counts[target[1]] = unit_counts.get(target[1], 0) + 1
        for file_id in target[3]:
            file_counts[file_id] = file_counts.get(file_id, 0) + 1
    modules = {}
    owners = {}
    by_id = {file.id: file for file in files}
    for module, unit, _, file_ids in targets:
        if (
            module_counts[module] > 1
            or unit_counts[unit] > 1
            or any(file_counts[i] > 1 for i in file_ids)
        ):
            continue
        if not file_ids:
            continue
        modules[module] = (unit, file_ids[0])
        for file_id in file_ids:
            owners[file_id] = (module, unit)
    if not modules:
        return []
    output = []
    for source in files:
        owner = owners.get(source.id)
        if owner is None or not candidate(source, "swift"):
            continue
        text = read_source(source)
        if text is None:
            continue
        plain = plain_swift_imports(source_lines(text))
        source_module, source_unit = owner
        for imp in imports_by_file.get(source.id, []):
            module = imp.specifier.split("/", 1)[0]
            target = modules.get(module)
            if (
                imp.specifier not in plain
                or target is None
                or module == source_module
                or target[0] == source_unit
            ):
                continue
            target_file = by_id.get(target[1])
            if target_file is not None:
                output.append(fact(source, imp, source_unit, (target_file, target[0])))
    return output


def repository_root(files) -> Path | None:
    if not files:
        return None
    root = files[0].physical
    for _ in Path(files[0].relative).parts:
        root = root.parent
    return root


def pbx_swift_targets(text: str, project_dir: Path, root: Path, by_relative):
    """Small OpenStep plist reader sufficient for PBX target/source references."""
    try:
        value = PbxParser(text).parse()
    except ValueError, IndexError:
        return []
    objects = value.get("objects", {}) if isinstance(value, dict) else {}
    if not isinstance(objects, dict):
        return []
    project_object = next(
        (
            obj
            for obj in objects.values()
            if isinstance(obj, dict) and obj.get("isa") == "PBXProject"
        ),
        None,
    )
    if not isinstance(project_object, dict) or not isinstance(
        project_object.get("mainGroup"), str
    ):
        return []
    refs = walk_pbx_groups(objects, project_object["mainGroup"], project_dir)
    results = []
    for key, obj in objects.items():
        if not isinstance(obj, dict) or obj.get("isa") != "PBXNativeTarget":
            continue
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        module = target_module(objects, obj, name)
        if module is None:
            continue
        sources = target_source_paths(objects, obj, refs)
        if not sources:
            continue
        unit = common_dir_relative(sources, root)
        if unit is None:
            continue
        ids = []
        for path in sorted(set(sources)):
            try:
                relative = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            row = by_relative.get(relative)
            if row is not None:
                ids.append(row.id)
        results.append((module, unit, key, sorted(set(ids))))
    return results


def walk_pbx_groups(objects, main_group, project_dir):
    refs = {}
    stack = [(main_group, project_dir)]
    seen = set()
    while stack:
        object_id, base = stack.pop()
        if object_id in seen:
            continue
        seen.add(object_id)
        obj = objects.get(object_id)
        if not isinstance(obj, dict):
            continue
        isa = obj.get("isa")
        if isa in {"PBXGroup", "PBXVariantGroup"}:
            directory = group_directory(
                obj.get("sourceTree"), obj.get("path"), base, project_dir
            )
            stack.extend(
                (child, directory)
                for child in obj.get("children", [])
                if isinstance(child, str)
            )
        elif isa == "PBXFileReference":
            name = obj.get("path") or obj.get("name")
            path = file_reference_path(obj.get("sourceTree"), name, base, project_dir)
            refs[object_id] = (path, isinstance(name, str) and name.endswith(".swift"))
    return refs


def group_directory(source_tree, path, base, project_dir):
    if source_tree in (None, "<group>"):
        directory = base
    elif source_tree in {"SOURCE_ROOT", "PROJECT_DIR"}:
        directory = project_dir
    elif source_tree == "<absolute>":
        directory = Path("/")
    else:
        return None
    return (
        directory / path
        if directory is not None and isinstance(path, str)
        else directory
    )


def file_reference_path(source_tree, name, base, project_dir):
    if not isinstance(name, str):
        return None
    if source_tree in (None, "<group>"):
        directory = base
    elif source_tree in {"SOURCE_ROOT", "PROJECT_DIR"}:
        directory = project_dir
    elif source_tree == "<absolute>":
        directory = Path("/")
    else:
        return None
    return directory / name if directory is not None else None


def target_source_paths(objects, target, refs):
    sources = []
    phases = target.get("buildPhases", [])
    if not isinstance(phases, list):
        return None
    for phase_id in phases:
        phase = objects.get(phase_id)
        if not isinstance(phase, dict):
            return None
        if phase.get("isa") != "PBXSourcesBuildPhase":
            continue
        for build_id in phase.get("files", []):
            build = objects.get(build_id)
            if not isinstance(build, dict):
                return None
            reference = refs.get(build.get("fileRef"))
            if reference is None:
                return None
            path, is_swift = reference
            if is_swift:
                if path is None:
                    return None
                sources.append(path)
    return sources or None


def target_module(objects, target, target_name):
    modules = set()
    list_id = target.get("buildConfigurationList")
    config_list = objects.get(list_id) if isinstance(list_id, str) else None
    configurations = (
        config_list.get("buildConfigurations", [])
        if isinstance(config_list, dict)
        else []
    )
    for config_id in configurations:
        config = objects.get(config_id)
        settings = config.get("buildSettings") if isinstance(config, dict) else None
        if not isinstance(settings, dict):
            continue
        value = settings.get("PRODUCT_MODULE_NAME", settings.get("PRODUCT_NAME"))
        if not isinstance(value, str):
            continue
        resolved = resolve_setting(value, target_name)
        if resolved is None:
            return None
        modules.add(sanitize_module(resolved))
    if len(modules) > 1:
        return None
    return next(iter(modules)) if modules else sanitize_module(target_name)


def resolve_setting(value, target_name):
    def replace(match):
        setting = match.group(1)
        if setting == "TARGET_NAME" or setting.startswith("TARGET_NAME:"):
            return target_name
        raise ValueError

    try:
        resolved = re.sub(r"\$\(([^)]*)\)", replace, value)
    except ValueError:
        return None
    return None if "${" in resolved else resolved


def common_dir_relative(paths, root):
    dirs = []
    for path in paths:
        absolute = Path(os.path.abspath(path))
        root_absolute = Path(os.path.abspath(root))
        if not absolute.is_relative_to(root_absolute):
            return None
        dirs.append(absolute.parent)
    if not dirs:
        return None
    common = dirs[0]
    for directory in dirs[1:]:
        while not directory.is_relative_to(common):
            common = common.parent
    try:
        relative = common.relative_to(Path(os.path.abspath(root))).as_posix()
    except ValueError:
        return None
    return relative or "."


def sanitize_module(name: str) -> str:
    module = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not module or module[0].isdigit():
        module = "_" + module
    return module


class PbxParser:
    """Parser for the dictionary/array/string subset of OpenStep plist syntax."""

    def __init__(self, text: str):
        self.text, self.i = text, 0

    def trivia(self):
        while self.i < len(self.text):
            if self.text[self.i].isspace():
                self.i += 1
            elif self.text.startswith("//", self.i):
                end = self.text.find("\n", self.i)
                self.i = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.i):
                end = self.text.find("*/", self.i + 2)
                self.i = len(self.text) if end < 0 else end + 2
            else:
                break

    def parse(self):
        value = self.value()
        self.trivia()
        return value

    def value(self):
        self.trivia()
        c = self.text[self.i]
        if c == "{":
            return self.dictionary()
        if c == "(":
            return self.array()
        if c == '"':
            return self.quoted()
        return self.bare()

    def dictionary(self):
        self.i += 1
        result = {}
        while True:
            self.trivia()
            if self.text[self.i] == "}":
                self.i += 1
                return result
            key = self.quoted() if self.text[self.i] == '"' else self.bare()
            self.trivia()
            if self.text[self.i] != "=":
                raise ValueError("expected =")
            self.i += 1
            value = self.value()
            self.trivia()
            if self.text[self.i] != ";":
                raise ValueError("expected ;")
            self.i += 1
            result[key] = value

    def array(self):
        self.i += 1
        values = []
        while True:
            self.trivia()
            if self.text[self.i] == ")":
                self.i += 1
                return values
            if self.text[self.i] == ",":
                self.i += 1
                continue
            values.append(self.value())

    def quoted(self):
        self.i += 1
        out = []
        while self.i < len(self.text):
            c = self.text[self.i]
            self.i += 1
            if c == '"':
                return "".join(out)
            if c == "\\" and self.i < len(self.text):
                c = self.text[self.i]
                self.i += 1
                c = {"n": "\n", "r": "\r", "t": "\t"}.get(c, c)
            out.append(c)
        raise ValueError("unterminated string")

    def bare(self):
        start = self.i
        while (
            self.i < len(self.text)
            and not self.text[self.i].isspace()
            and self.text[self.i] not in '{}()=;,"'
        ):
            self.i += 1
        if (
            self.i < len(self.text)
            and self.text[self.i] == "("
            and self.text[start : self.i].endswith("$")
        ):
            depth = 0
            while self.i < len(self.text):
                if self.text[self.i] == "(":
                    depth += 1
                elif self.text[self.i] == ")":
                    depth -= 1
                    self.i += 1
                    if depth == 0:
                        break
                    continue
                self.i += 1
        if self.i == start:
            raise ValueError("expected value")
        return self.text[start : self.i]
