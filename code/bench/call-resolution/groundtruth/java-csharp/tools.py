"""Run isolated JDK and Roslyn call-target exporters."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from xml.etree import ElementTree

from pipeline import export_tool_output, verification_stub, write_jsonl

HERE = Path(__file__).resolve().parent
Runner = Callable[..., subprocess.CompletedProcess[str]]
EXPORTERS = {"java": "JavacTargets.java", "csharp": "RoslynTargets.cs"}


def exporter_digest(language: str) -> str:
    """Digest of the sources that determine a record file's content."""
    digest = hashlib.sha256()
    for name in (EXPORTERS[language], "tools.py", "pipeline.py"):
        digest.update((HERE / name).read_bytes())
    return digest.hexdigest()


def run_java(
    repo: str,
    repo_root: Path,
    source_root: Path,
    output: Path,
    env_root: Path,
    *,
    runner: Runner | None = None,
) -> list[dict[str, object]]:
    """Compile the javac visitor and save compiler-derived records."""
    classes = env_root / "javac-classes"
    classes.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "javac",
            "-proc:none",
            "-Xlint:none",
            "-d",
            str(classes),
            str(HERE / "JavacTargets.java"),
        ],
        env=_java_env(env_root),
        runner=runner,
    )
    result = _run(
        [
            "java",
            "-cp",
            str(classes),
            "JavacTargets",
            repo,
            str(repo_root),
            str(source_root),
        ],
        env=_java_env(env_root),
        runner=runner,
    )
    return _save_result(result.stdout, repo, "java", "javac", output)


def run_csharp(  # noqa: PLR0913
    repo: str,
    repo_root: Path,
    source_root: Path,
    output: Path,
    env_root: Path,
    references: Path | None = None,
    *,
    runner: Runner | None = None,
) -> list[dict[str, object]]:
    """Run Roslyn's semantic model with caches and build outputs under env_root."""
    project = env_root / "roslyn-runner"
    project.mkdir(parents=True, exist_ok=True)
    project_file = project / "Runner.csproj"
    project_file.write_text(_project_xml(env_root))
    helper_link = project / "RoslynTargets.cs"
    helper_link.unlink(missing_ok=True)
    helper_link.symlink_to(HERE / "RoslynTargets.cs")
    reference_list = project / "references.txt"
    reference_list.write_text(
        "\n".join(str(path.resolve()) for path in (references or Path()).glob("*.dll"))
        if references is not None
        else ""
    )
    global_usings = _global_usings_file(repo_root, source_root, env_root)
    extra_sources = project / "extra-sources.txt"
    extra_sources.write_text(
        "" if global_usings is None else f"{global_usings.resolve()}\n"
    )
    env = _dotnet_env(env_root)
    _run(["dotnet", "build", str(project_file)], env=env, runner=runner)
    result = _run(
        [
            "dotnet",
            "exec",
            str(env_root / "roslyn-bin" / "net10.0" / "Runner.dll"),
            repo,
            str(repo_root.resolve()),
            str(source_root.resolve()),
            str(reference_list),
            str(extra_sources),
        ],
        env=env,
        runner=runner,
    )
    return _save_result(result.stdout, repo, "csharp", "roslyn", output)


def _global_usings_file(
    repo_root: Path, source_root: Path, env_root: Path
) -> Path | None:
    """Write the compilation's global usings: implicit SDK usings and declared ones."""
    usings = set(_declared_usings(repo_root, source_root, env_root))
    properties = _msbuild_properties(repo_root, source_root, env_root)
    if properties.get("implicitusings", "").lower() in {"enable", "true"}:
        dotnet_root = Path(_dotnet_root(dict(os.environ)))
        usings.update(_sdk_usings(_project_sdks(repo_root, source_root), dotnet_root))
    if not usings:
        return None
    path = env_root / "global-usings" / f"{source_root.name}.g.cs"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{using}\n" for using in sorted(usings)))
    return path


def _project_sdks(repo_root: Path, source_root: Path) -> set[str]:
    sdks = set()
    for name in _root_project_names(repo_root, source_root):
        path = repo_root / name
        if not path.is_file():
            continue
        match = re.search(
            r'<Project[^>]*Sdk="([^"]+)"', path.read_text(errors="replace")
        )
        if match:
            sdks.update(
                part.strip() for part in match.group(1).split(";") if part.strip()
            )
    return sdks


def _sdk_usings(sdks: set[str], dotnet_root: Path) -> set[str]:
    usings = set()
    roots = sorted((dotnet_root / "sdk").glob("*/Sdks"))
    for sdk in sorted(sdks):
        for root in roots:
            directory = root / sdk
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if path.suffix not in {".props", ".targets"} or not path.is_file():
                    continue
                text = path.read_text(errors="replace")
                usings.update(
                    f"global using {name};"
                    for name in re.findall(r'<Using Include="([^"]+)"', text)
                )
    return usings


def _declared_usings(repo_root: Path, source_root: Path, env_root: Path) -> set[str]:
    texts = [text for _, text in _props_files(repo_root, source_root, env_root)]
    for name in _root_project_names(repo_root, source_root):
        path = repo_root / name
        if path.is_file():
            texts.append(path.read_text(errors="replace"))
    usings = set()
    for text in texts:
        for node in re.findall(r"<Using\b[^>]*>", text):
            include = re.search(r'Include="([^"]+)"', node)
            if include is None or "$(" in include.group(1):
                continue
            alias = re.search(r'Alias="([^"]+)"', node)
            if alias:
                usings.add(f"global using {alias.group(1)} = {include.group(1)};")
            elif re.search(r'Static="[Tt]rue"', node):
                usings.add(f"global using static {include.group(1)};")
            else:
                usings.add(f"global using {include.group(1)};")
    return usings


def prepare_csharp_references(
    repo_root: Path, source_root: Path, env_root: Path
) -> Path:
    """Collect compiler references from framework packs and restored packages."""
    reference_root = env_root / "references" / source_root.name
    shutil.rmtree(reference_root, ignore_errors=True)
    reference_root.mkdir(parents=True, exist_ok=True)
    owned = {Path(name).stem for name in _root_project_names(repo_root, source_root)}
    _link_framework_references(env_root, reference_root, owned)
    _restore_package_references(repo_root, source_root, env_root, reference_root, owned)
    return reference_root


def _link_framework_references(env_root: Path, output: Path, owned: set[str]) -> None:
    """Link the SDK's framework-reference assemblies (ASP.NET Core and friends)."""
    packs = Path(_dotnet_root(dict(os.environ))) / "packs"
    for pack in sorted(packs.glob("*.Ref")):
        if pack.name == "Microsoft.NETCore.App.Ref":
            continue
        for dll in sorted(pack.glob("*/ref/net*/*.dll")):
            _link_reference(dll, output, owned)


def _restore_package_references(
    repo_root: Path, source_root: Path, env_root: Path, output: Path, owned: set[str]
) -> None:
    """Restore the projects' PackageReferences and link their compile assemblies."""
    packages = _package_versions(repo_root, source_root, env_root)
    if not packages:
        return
    project_dir = env_root / "package-restore" / source_root.name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "Packages.csproj"
    env = _dotnet_env(env_root)
    for _ in range(6):
        project_file.write_text(_packages_xml(packages))
        result = subprocess.run(
            [
                "dotnet",
                "restore",
                str(project_file),
                "--packages",
                str(env_root / "nuget-packages"),
                "--source",
                "https://api.nuget.org/v3/index.json",
                "--verbosity",
                "quiet",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if not result.returncode:
            break
        unusable = _unusable_packages(result.stdout + result.stderr) & packages.keys()
        if not unusable:
            (output / "package-error.txt").write_text(result.stdout + result.stderr)
            break
        for name in unusable:
            del packages[name]
    assets = project_dir / "obj" / "project.assets.json"
    if assets.is_file():
        _link_compile_assets(assets, output, owned)


def _link_compile_assets(assets: Path, output: Path, owned: set[str]) -> None:
    data = json.loads(assets.read_text())
    libraries = data.get("libraries", {})
    package_roots = [Path(root) for root in data.get("packageFolders", {})]
    for target in data.get("targets", {}).values():
        for name, library in target.items():
            package_path = libraries.get(name, {}).get("path")
            if not package_path:
                continue
            for reference in library.get("compile", {}):
                if reference.endswith("_._"):
                    continue
                for root in package_roots:
                    dll = root / package_path / reference
                    if dll.is_file():
                        _link_reference(dll, output, owned)


def _root_project_names(repo_root: Path, source_root: Path) -> list[str]:
    projects = sorted(source_root.rglob("*.csproj"))
    if not projects:
        for parent in source_root.parents:
            projects = sorted(parent.glob("*.csproj"))
            if projects or parent == repo_root:
                break
    return [path.relative_to(repo_root).as_posix() for path in projects]


def _pin_text(repo_root: Path, env_root: Path, relative: str) -> str | None:
    """Read a pinned file from the checkout or fetch it from the pinned commit."""
    path = repo_root / relative
    if path.is_file():
        return path.read_text(errors="replace")
    cached = env_root / "pin-files" / repo_root.name / relative
    if cached.is_file():
        return cached.read_text(errors="replace")
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{relative}"],
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(env_root),
    )
    if result.returncode:
        return None
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(result.stdout)
    return result.stdout


def _git_env(env_root: Path) -> dict[str, str]:
    return {"HOME": str(env_root / "git-home"), "GIT_TERMINAL_PROMPT": "0"}


def _pin_listing(repo_root: Path, env_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(env_root),
    )
    return result.stdout.splitlines() if not result.returncode else []


def _project_texts(
    repo_root: Path, source_root: Path, env_root: Path
) -> dict[str, str]:
    """Read the source root's projects and the projects they reference."""
    texts: dict[str, str] = {}
    queue = _root_project_names(repo_root, source_root)
    while queue and len(texts) < 300:
        name = queue.pop()
        if name in texts:
            continue
        text = _pin_text(repo_root, env_root, name)
        if text is None:
            continue
        texts[name] = text
        queue.extend(_project_references(repo_root, name, text))
    return texts


def _project_references(repo_root: Path, name: str, text: str) -> list[str]:
    root = _xml_root(text)
    if root is None:
        return []
    references = []
    for node in root.iter("ProjectReference"):
        include = (node.get("Include") or "").replace("\\", "/")
        if "$(" in include and "$(RepoRoot)" not in include:
            continue
        include = include.replace("$(RepoRoot)", f"{repo_root}/")
        prefix = f"{repo_root}/"
        if include.startswith("/"):
            if not include.startswith(prefix):
                continue
            include = include[len(prefix) :]
        else:
            include = posixpath.join(posixpath.dirname(name), include)
        include = posixpath.normpath(include)
        if include.endswith(".csproj") and not include.startswith("../"):
            references.append(include)
    return references


def _package_versions(
    repo_root: Path, source_root: Path, env_root: Path
) -> dict[str, str]:
    """Map PackageReference ids reachable from the source root to versions."""
    properties = _msbuild_properties(repo_root, source_root, env_root)
    central = _central_versions(repo_root, source_root, env_root)
    packages: dict[str, str] = {}
    for text in _project_texts(repo_root, source_root, env_root).values():
        for name, version in _package_items(text):
            resolved = _resolve_version(version, properties) or _resolve_version(
                central.get(name.lower(), ""), properties
            )
            if resolved and name not in packages:
                packages[name] = resolved
    return packages


def _xml_root(text: str) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(text)  # noqa: S314 - Input is project metadata from the pinned repository corpus.
    except ElementTree.ParseError:
        return None


def _package_items(text: str) -> list[tuple[str, str]]:
    root = _xml_root(text)
    if root is None:
        return []
    items = []
    for node in root.iter("PackageReference"):
        name = node.get("Include") or ""
        if not name or "$(" in name:
            continue
        version = node.get("Version") or ""
        if not version:
            child = node.find("Version")
            version = child.text if child is not None and child.text else ""
        items.append((name, version))
    return items


def _central_versions(
    repo_root: Path, source_root: Path, env_root: Path
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, text in _props_files(repo_root, source_root, env_root):
        if posixpath.basename(name) != "Directory.Packages.props":
            continue
        root = _xml_root(text)
        if root is None:
            continue
        for node in root.iter("PackageVersion"):
            package = (node.get("Include") or "").lower()
            version = node.get("Version") or ""
            if package and version and package not in versions:
                versions[package] = version
    return versions


def _msbuild_properties(
    repo_root: Path, source_root: Path, env_root: Path
) -> dict[str, str]:
    """Collect plain MSBuild property values that package versions refer to."""
    properties: dict[str, str] = {}
    for _, text in _props_files(repo_root, source_root, env_root):
        for name, value in re.findall(r"<([A-Za-z_]\w*)>([^<>]+)</\1>", text):
            properties[name.lower()] = value.strip()
    return properties


_MSBUILD_SUFFIXES = (".props", ".targets")


def _props_files(
    repo_root: Path, source_root: Path, env_root: Path
) -> list[tuple[str, str]]:
    """Read the repository's MSBuild property files, following their imports.

    Both `.props` and `.targets` files are read: SDK-style repositories put
    shared settings such as `ImplicitUsings` in targets files that MSBuild
    imports by convention (`Directory.Build.targets`) or through a property
    (`$(RepositoryEngineeringDir)targets/...`), so neither an explicit
    `<Import>` nor the checkout cone reaches them.
    """
    directories = {repo_root, source_root, *source_root.parents}
    names = {
        path.relative_to(repo_root).as_posix()
        for directory in directories
        for suffix in _MSBUILD_SUFFIXES
        for path in directory.glob(f"*{suffix}")
        if path.parent == repo_root or repo_root in path.parents
    }
    names.update(
        name
        for name in _pin_listing(repo_root, env_root)
        if name.endswith(_MSBUILD_SUFFIXES) and "/eng/" in f"/{name}"
    )
    files: dict[str, str] = {}
    queue = sorted(names)
    while queue and len(files) < 200:
        name = queue.pop(0)
        if name in files:
            continue
        text = _pin_text(repo_root, env_root, name)
        if text is None:
            continue
        files[name] = text
        queue.extend(
            imported for imported in _imports(name, text) if imported not in files
        )
    return sorted(files.items())


def _imports(name: str, text: str) -> list[str]:
    """Resolve the MSBuild files a property file imports."""
    directory = posixpath.dirname(name)
    imported = []
    for project in re.findall(r"<Import[^>]*Project=\"([^\"]+)\"", text):
        include = project.replace("\\", "/")
        include = include.replace("$(MSBuildThisFileDirectory)", f"{directory}/")
        if "$(" in include:
            continue
        if not include.startswith("/"):
            include = posixpath.join(directory, include)
        include = posixpath.normpath(include)
        if include.startswith("../"):
            continue
        imported.append(include)
    return imported


def _resolve_version(version: str, properties: Mapping[str, str]) -> str:
    for _ in range(5):
        if "$(" not in version:
            break
        version = re.sub(
            r"\$\(([\w.]+)\)",
            lambda match: properties.get(match.group(1).lower(), ""),
            version,
        )
    return version.strip()


def _unusable_packages(message: str) -> set[str]:
    names = set()
    for match in re.finditer(
        r"error (?:NU1101|NU1102|NU1103|NU1202)[^\n]*?"
        r"(?:package |Package )([\w\-]+(?:\.[\w\-]+)*)",
        message,
    ):
        names.add(match.group(1))
    return names


def _packages_xml(packages: Mapping[str, str]) -> str:
    references = "".join(
        f'    <PackageReference Include="{name}" Version="{version}" />\n'
        for name, version in sorted(packages.items())
    )
    return (
        '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
        "    <TargetFramework>net10.0</TargetFramework>\n"
        "    <ManagePackageVersionsCentrally>false</ManagePackageVersionsCentrally>\n"
        "    <ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>\n"
        "    <ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>\n"
        "    <NuGetAudit>false</NuGetAudit>\n"
        "  </PropertyGroup>\n  <ItemGroup>\n"
        f"{references}"
        "  </ItemGroup>\n</Project>\n"
    )


def _link_reference(source: Path, output: Path, owned: set[str]) -> None:
    """Link one assembly per file name; skip assemblies the repository builds."""
    if source.stem in owned:
        return
    target = output / source.name
    if not target.exists():
        target.symlink_to(source.resolve())


def _save_result(
    stdout: str, repo: str, language: str, tool: str, output: Path
) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    records = export_tool_output(
        ({**row, "truth_source": row.get("truth_source", tool)} for row in rows),
        repo=repo,
        language=language,
    )
    write_jsonl(output, records)
    output.with_suffix(".stamp").write_text(exporter_digest(language) + "\n")
    stubs = [
        verification_stub(row) for row in records if row["ground_truth"] == "unknown"
    ]
    if stubs:
        write_jsonl(output.with_name(output.stem + "-human-review.jsonl"), stubs)
    return records


def _run(
    command: list[str], *, env: dict[str, str], runner: Runner | None = None
) -> subprocess.CompletedProcess[str]:
    invoke = runner or subprocess.run
    result = invoke(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def _java_env(env_root: Path) -> dict[str, str]:
    env = _isolated_env(env_root)
    env.update(
        MAVEN_OPTS=f"-Dmaven.repo.local={env_root / 'maven-repo'}",
        GRADLE_USER_HOME=str(env_root / "gradle"),
    )
    return env


def _dotnet_env(env_root: Path) -> dict[str, str]:
    env = _isolated_env(env_root)
    cli_home = env_root / "dotnet-home"
    package_home = env_root / "nuget-packages"
    cli_home.mkdir(parents=True, exist_ok=True)
    package_home.mkdir(parents=True, exist_ok=True)
    env.update(
        DOTNET_ROOT=_dotnet_root(env),
        DOTNET_CLI_HOME=str(cli_home),
        NUGET_PACKAGES=str(package_home),
    )
    return env


def _isolated_env(env_root: Path) -> dict[str, str]:
    paths = {
        "HOME": env_root / "home",
        "XDG_CACHE_HOME": env_root / "xdg-cache",
        "XDG_CONFIG_HOME": env_root / "xdg-config",
        "XDG_DATA_HOME": env_root / "xdg-data",
        "VARDE_CONFIG_DIR": env_root / "varde-config",
        "TMPDIR": env_root / "tmp",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({key: str(value) for key, value in paths.items()})
    return env


def _dotnet_root(env: Mapping[str, str]) -> str:
    """Resolve DOTNET_ROOT from the environment or the dotnet host on PATH."""
    configured = env.get("DOTNET_ROOT")
    if configured and (Path(configured) / "packs").is_dir():
        return str(Path(configured).resolve())
    executable = shutil.which("dotnet", path=env.get("PATH"))
    if executable is None:
        raise RuntimeError("dotnet is not available on PATH and DOTNET_ROOT is unset")
    host = Path(executable).resolve().parent
    for candidate in [host, *list(host.parents)[:3]]:
        for root in (candidate, candidate / "libexec"):
            if (root / "packs").is_dir() or (root / "sdk").is_dir():
                return str(root)
    raise RuntimeError(f"cannot derive DOTNET_ROOT from {executable}")


def _project_xml(env_root: Path) -> str:
    intermediate = env_root / "roslyn-obj"
    output = env_root / "roslyn-bin"
    return (
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <PropertyGroup>\n"
        "    <OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>\n"
        "    <ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>\n"
        f"    <BaseIntermediateOutputPath>{intermediate}</BaseIntermediateOutputPath>\n"
        f"    <OutputPath>{output}</OutputPath>\n"
        "  </PropertyGroup>\n"
        "  <ItemGroup>\n"
        '    <Reference Include="Microsoft.CodeAnalysis"><HintPath>$(MSBuildSDKsPath)/'
        "../Roslyn/bincore/Microsoft.CodeAnalysis.dll</HintPath></Reference>\n"
        '    <Reference Include="Microsoft.CodeAnalysis.CSharp"><HintPath>'
        "$(MSBuildSDKsPath)/"
        "../Roslyn/bincore/Microsoft.CodeAnalysis.CSharp.dll</HintPath>"
        "</Reference>\n"
        "  </ItemGroup>\n"
        "</Project>"
    )
