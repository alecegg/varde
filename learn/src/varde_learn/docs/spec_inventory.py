"""Verified, reusable inventory of repository sources for specification checks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

import yaml

CACHE_VERSION = 4
FULL_AFTER_REUSES = 10
FULL_AFTER_SECONDS = 24 * 60 * 60
Git = Callable[[Path, tuple[str, ...]], bytes]


@dataclass
class Domain:
    domain: str
    status: str
    reason: str
    source_roots: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Cache:
    version: int
    repository: str
    knowledge: str
    head: str
    ignore_hash: str
    paths: dict[str, str]
    untracked: list[str]
    spec_hashes: dict[str, str]
    domains: list[Domain]
    pending_architecture_paths: list[str]
    acknowledged_architecture_paths: dict[str, str]
    validated_at: int
    reuses: int


def inventory(
    repository: Path,
    knowledge: Path,
    working: Path,
    *,
    refresh: bool = False,
    acknowledge_architecture_paths: Iterable[str] = (),
    clock: Callable[[], int | float] = time.time,
    git: Git | None = None,
) -> dict:
    git = git or _default_git
    repository = repository.resolve(strict=True)
    knowledge = knowledge.resolve(strict=True)
    working = working.resolve(strict=True)
    cache_dir = working / "spec-inventory"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = blob_hash(f"{repository}\0{knowledge}".encode())
    cache_path = cache_dir / f"{key}.json"
    previous = _read_cache(cache_path, repository, knowledge)
    head = git_text(git, repository, "rev-parse", "HEAD")
    ignore_hash = ignore_fingerprint(repository, git)
    current_paths = {
        path
        for path in git_paths(
            git,
            repository,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        if (repository / path).is_file()
    }
    untracked = set(
        git_paths(git, repository, "ls-files", "--others", "--exclude-standard", "-z")
    )
    hashes_for_specs = spec_hashes(knowledge)
    prior_paths = previous.paths.copy() if previous else None
    pending = set(previous.pending_architecture_paths) if previous else set()
    acknowledged = previous.acknowledged_architecture_paths.copy() if previous else {}
    if previous and previous.spec_hashes.get(
        "specs/architecture.md"
    ) != hashes_for_specs.get("specs/architecture.md"):
        pending.clear()
        acknowledged.clear()
    pending_path_removed = any(path not in current_paths for path in pending)
    pending.intersection_update(current_paths)
    if previous:
        pending.update(current_paths.difference(previous.paths))
    else:
        pending.update(untracked)
    pending.update(
        architecture_additions_since_index(repository, knowledge, current_paths, git)
    )

    now = int(clock())
    unreliable_index = any(
        entry[:1].islower() or entry.startswith(b"S")
        for entry in git_bytes(git, repository, "ls-files", "-v", "-z").split(b"\0")
        if entry
    )
    due = bool(
        previous
        and (
            previous.reuses >= FULL_AFTER_REUSES
            or now - previous.validated_at >= FULL_AFTER_SECONDS
        )
    )
    full = bool(
        refresh
        or previous is None
        or due
        or unreliable_index
        or pending_path_removed
        or (
            previous
            and (
                previous.ignore_hash != ignore_hash
                or previous.spec_hashes.get("specs/index.md")
                != hashes_for_specs.get("specs/index.md")
            )
        )
    )
    if full:
        cache = full_inventory(
            repository,
            knowledge,
            head,
            current_paths,
            untracked,
            hashes_for_specs,
            ignore_hash,
            now,
            git,
        )
    else:
        if previous is None:
            raise AssertionError("incremental inventory requires previous cache")
        try:
            cache = incremental_inventory(
                previous,
                repository,
                knowledge,
                head,
                current_paths,
                untracked,
                hashes_for_specs,
                ignore_hash,
                now,
                git,
            )
        except Exception:
            full = True
            cache = full_inventory(
                repository,
                knowledge,
                head,
                current_paths,
                untracked,
                hashes_for_specs,
                ignore_hash,
                now,
                git,
            )

    cache.pending_architecture_paths = sorted(pending)
    cache.acknowledged_architecture_paths = acknowledged
    for path in acknowledge_architecture_paths:
        value = path.replace("\\", "/")
        if not safe_relative(value) or value not in cache.paths:
            raise ValueError(
                (  # noqa: UP034 - Explicit grouping is required for split message text.
                    "acknowledged architecture path must be an existing repository "
                    f"file: {value}"
                )
            )
        if is_definite_declaration(value):
            raise ValueError(
                f"architecture declaration cannot be acknowledged away: {value}"
            )
        cache.acknowledged_architecture_paths[value] = cache.paths[value]

    architecture = next(
        (domain for domain in cache.domains if domain.domain == "architecture"), None
    )
    inspect_paths: list[str] = []
    if architecture:
        if (
            architecture.status == "inspect"
            and architecture.reason == "new path needs architecture classification"
        ):
            architecture.status, architecture.reason = "reuse", "verified provenance"
        inspect_paths = sorted(
            {
                path
                for path in [
                    *cache.pending_architecture_paths,
                    *cache.acknowledged_architecture_paths,
                ]
                if path in cache.paths
                and not is_definite_declaration(path)
                and not any(contains(root, path) for root in architecture.source_roots)
                and cache.acknowledged_architecture_paths.get(path)
                != cache.paths.get(path)
            }
        )
        if architecture.status == "reuse" and inspect_paths:
            architecture.status, architecture.reason = (
                "inspect",
                "new path needs architecture classification",
            )
    overlapping, unmatched = classify_paths(cache.paths, cache.domains)
    changed_for_unclassified = None if full else prior_paths
    unclassified = unclassified_paths(
        cache.paths, cache.domains, changed_for_unclassified
    )
    architecture_status = (
        architecture.status
        if architecture
        else (
            "missing"
            if any(is_definite_declaration(p) for p in cache.paths)
            else "none"
        )
    )
    candidates = (
        []
        if architecture
        else sorted(
            p
            for p in cache.paths
            if is_declaration(p) and not is_definite_declaration(p)
        )
    )
    data = {
        "cache_hit": not full,
        "full_validation_due": due,
        "full_validation": full,
        "domains": [asdict(domain) for domain in cache.domains],
        "architecture": asdict(architecture) if architecture else None,
        "architecture_status": architecture_status,
        "architecture_candidates": candidates,
        "architecture_inspect_paths": inspect_paths,
        "overlapping": overlapping,
        "unmatched": unmatched,
        "unclassified_paths": unclassified,
        "missing": missing_domains(cache.paths, cache.domains),
    }
    write_cache(cache_path, cache)
    return data


def full_inventory(
    repository: Path,
    knowledge: Path,
    head: str,
    paths: set[str],
    untracked: set[str],
    specs: dict[str, str],
    ignore_hash: str,
    now: int,
    git: Git,
) -> Cache:
    hashes = {path: hash_file(repository, path) for path in sorted(paths)}
    domains = verify_domains(repository, knowledge, hashes, None, set())
    return Cache(
        CACHE_VERSION,
        str(repository),
        str(knowledge),
        head,
        ignore_hash,
        hashes,
        sorted(untracked),
        specs,
        domains,
        [],
        {},
        now,
        0,
    )


def incremental_inventory(
    cache: Cache,
    repository: Path,
    knowledge: Path,
    head: str,
    paths: set[str],
    untracked: set[str],
    specs: dict[str, str],
    ignore_hash: str,
    now: int,
    git: Git,
) -> Cache:
    changed: set[str] = set()
    if cache.head != head:
        changed.update(
            git_paths(git, repository, "diff", "--name-only", "-z", cache.head, head)
        )
    changed.update(git_paths(git, repository, "diff", "--name-only", "--cached", "-z"))
    changed.update(git_paths(git, repository, "diff", "--name-only", "-z"))
    changed.update(set(cache.paths).difference(paths))
    changed.update(
        path for path in paths if path not in cache.paths or path in untracked
    )
    if any(is_ignore_rule(path) for path in changed):
        raise ValueError("ignore policy changed; full inventory required")
    hashes = {path: digest for path, digest in cache.paths.items() if path in paths}
    for path in sorted(changed):
        if path in paths:
            digest = hash_file(repository, path)
            if hashes.get(path) == digest:
                changed.discard(path)
            hashes[path] = digest
    changed_specs = {
        path for path, digest in specs.items() if cache.spec_hashes.get(path) != digest
    }
    changed_specs.update(set(cache.spec_hashes).difference(specs))
    domains = verify_domains(
        repository, knowledge, hashes, cache.domains, changed.union(changed_specs)
    )
    old_names = {d.domain for d in cache.domains if d.domain != "architecture"}
    new_names = {d.domain for d in domains if d.domain != "architecture"}
    architecture = next((d for d in domains if d.domain == "architecture"), None)
    if old_names != new_names and architecture:
        architecture.status, architecture.reason = "stale", "domain set changed"
    cache.head, cache.ignore_hash, cache.paths = head, ignore_hash, hashes
    cache.untracked, cache.spec_hashes, cache.domains = (
        sorted(untracked),
        specs,
        domains,
    )
    cache.reuses += 1
    if cache.reuses > FULL_AFTER_REUSES or now < cache.validated_at:
        raise ValueError("cache validation interval is uncertain")
    return cache


def verify_domains(
    repository: Path,
    knowledge: Path,
    paths: dict[str, str],
    previous: list[Domain] | None,
    changed: set[str],
) -> list[Domain]:
    specs = knowledge / "specs"
    if not specs.is_dir():
        return []
    domains: list[Domain] = []
    for path in specs.iterdir():
        if path.suffix != ".md" or path.name == "index.md":
            continue
        domain = path.stem
        mapping = parse_spec(path.read_bytes())
        roots = strings(mapping, "source_roots") or []
        sources = source_paths(mapping) or []
        relevant = (
            f"specs/{domain}.md" in changed
            or "specs/index.md" in changed
            or any(
                any(contains(root, changed_path) for root in roots)
                or changed_path in sources
                or (domain == "architecture" and is_declaration(changed_path))
                for changed_path in changed
            )
        )
        saved = next((item for item in previous or [] if item.domain == domain), None)
        if not relevant and saved:
            domains.append(saved)
        else:
            domains.append(verify_domain(domain, mapping, paths))
    return sorted(domains, key=lambda item: item.domain)


def verify_domain(domain: str, mapping: object, paths: dict[str, str]) -> Domain:
    result = Domain(domain, "stale", "malformed or incomplete specification provenance")
    if not isinstance(mapping, dict):
        return result
    roots = strings(mapping, "source_roots")
    covered = strings(mapping, "covered_paths")
    sources = source_entries(mapping)
    expected = mapping.get("source_hash")
    if (
        roots is None
        or covered is None
        or sources is None
        or not isinstance(expected, str)
    ):
        return result
    if not roots or any(not safe_relative(root) for root in roots):
        return result
    result.source_roots = roots
    result.sources = [path for path, _ in sources]
    actual_covered = sorted(
        path for path in paths if any(contains(root, path) for root in roots)
    )
    if actual_covered != covered:
        result.reason = "stale covered_paths"
        return result
    if domain == "architecture" and any(
        is_definite_declaration(path)
        and not any(contains(root, path) for root in roots)
        for path in paths
    ):
        result.reason = "architecture declaration outside source_roots"
        return result
    pairs: list[tuple[str, str]] = []
    for path, recorded in sources:
        if (
            not safe_relative(path)
            or not any(contains(root, path) for root in roots)
            or paths.get(path) != recorded
        ):
            result.reason = f"stale source: {path}"
            return result
        pairs.append((path, recorded))
    aggregate = "".join(path + digest for path, digest in sorted(pairs)).encode()
    if blob_hash(aggregate) != expected:
        result.reason = "stale source_hash"
        return result
    result.status, result.reason = "reuse", "verified provenance"
    return result


def parse_spec(data: bytes) -> object | None:
    try:
        text = data.decode("utf-8")
        if not text.startswith("---\n") or "\n---" not in text[4:]:
            return None
        return yaml.safe_load(text[4:].split("\n---", 1)[0])
    except UnicodeDecodeError, yaml.YAMLError:
        return None


def strings(value: object, key: str) -> list[str] | None:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get(key), list)
        or not all(isinstance(item, str) for item in value[key])
    ):
        return None
    return value[key]


def source_entries(value: object) -> list[tuple[str, str]] | None:
    if not isinstance(value, dict) or not isinstance(value.get("sources"), list):
        return None
    result = []
    for item in value["sources"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("hash"), str)
        ):
            return None
        result.append((item["path"], item["hash"]))
    return result


def source_paths(value: object) -> list[str] | None:
    entries = source_entries(value)
    return [path for path, _ in entries] if entries is not None else None


def contains(root: str, path: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def safe_relative(path: str) -> bool:
    candidate = PurePosixPath(path)
    return (
        bool(path)
        and not candidate.is_absolute()
        and all(part not in ("", ".", "..") for part in candidate.parts)
    )


def classify_paths(
    paths: dict[str, str], domains: list[Domain]
) -> tuple[list[str], list[str]]:
    overlapping, unmatched = [], []
    for path in sorted(paths):
        if not is_source_candidate(path):
            continue
        owners = sum(
            domain.domain != "architecture"
            and any(contains(root, path) for root in domain.source_roots)
            for domain in domains
        )
        if owners > 1:
            overlapping.append(path)
        if owners == 0:
            unmatched.append(path)
    return overlapping, unmatched


def unclassified_paths(
    paths: dict[str, str], domains: list[Domain], previous: dict[str, str] | None
) -> list[str]:
    return [
        path
        for path in sorted(paths)
        if (previous is None or previous.get(path) != paths[path])
        and not any(
            domain.domain != "architecture"
            and any(contains(root, path) for root in domain.source_roots)
            for domain in domains
        )
    ]


def architecture_additions_since_index(
    repository: Path, knowledge: Path, current_paths: set[str], git: Git
) -> set[str]:
    if (
        not (knowledge / "specs/architecture.md").is_file()
        or not (knowledge / "specs/index.md").exists()
    ):
        return set()
    parsed = parse_spec((knowledge / "specs/index.md").read_bytes())
    commit = parsed.get("source_commit") if isinstance(parsed, dict) else None
    if not isinstance(commit, str):
        return set(current_paths)
    try:
        added = git_paths(
            git,
            repository,
            "diff",
            "--name-only",
            "--diff-filter=A",
            "-z",
            commit,
            "HEAD",
        )
    except Exception:
        return set(current_paths)
    return added.intersection(current_paths)


def missing_domains(paths: dict[str, str], domains: list[Domain]) -> list[str]:
    _, unmatched = classify_paths(paths, domains)
    return sorted(
        {name for path in unmatched if (name := candidate_domain(path)) is not None}
    )


def is_source_candidate(path: str) -> bool:
    extension = path.rsplit("/", 1)[-1].rsplit(".", 1)
    return (
        len(extension) == 2
        and extension[1]
        in {
            "rs",
            "py",
            "ts",
            "tsx",
            "js",
            "mjs",
            "go",
            "java",
            "swift",
            "kt",
            "c",
            "cc",
            "cpp",
            "h",
            "sh",
        }
    ) or is_definite_declaration(path)


def candidate_domain(path: str) -> str | None:
    parts = path.split("/")
    if "src" in parts:
        position = parts.index("src")
        if position == 0 and len(parts) > 2:
            return f"src/{parts[1]}"
        return "/".join(parts[: max(position, 1)])
    parent = PurePosixPath(path).parent.as_posix()
    return parent if parent != "." else None


def is_ignore_rule(path: str) -> bool:
    return path == ".gitignore" or path.endswith("/.gitignore")


def ignore_fingerprint(repository: Path, git: Git) -> str:
    location = Path(
        git_text(git, repository, "rev-parse", "--git-path", "info/exclude")
    )
    path = location if location.is_absolute() else repository / location
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    return blob_hash(data)


def is_declaration(path: str) -> bool:
    if is_definite_declaration(path):
        return True
    name = path.rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return extension in {"yaml", "yml", "toml", "json", "tf", "tfvars", "hcl", "nix"}


def is_definite_declaration(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return name in {
        "Cargo.toml",
        "package.json",
        "pyproject.toml",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "go.mod",
        "Chart.yaml",
    } or (
        extension in {"yaml", "yml", "json", "toml", "tf", "tfvars", "hcl", "nix"}
        and path.startswith(
            (".github/workflows/", "deploy/", "infra/", "k8s/", "helm/", "terraform/")
        )
    )


def spec_hashes(knowledge: Path) -> dict[str, str]:
    directory = knowledge / "specs"
    return (
        {
            f"specs/{path.name}": blob_hash(path.read_bytes())
            for path in directory.iterdir()
            if directory.is_dir() and path.suffix == ".md"
        }
        if directory.is_dir()
        else {}
    )


def hash_file(repository: Path, relative: str) -> str:
    if not safe_relative(relative):
        raise ValueError(f"unsafe inventory path: {relative}")
    path = repository / relative
    if not path.is_file():
        raise FileNotFoundError(f"inventory file disappeared: {path}")
    if not path.resolve().is_relative_to(repository):
        raise ValueError(f"inventory path escapes repository: {relative}")
    return blob_hash(path.read_bytes())


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()  # noqa: S324 - Git object IDs require SHA-1 compatibility.


def _default_git(repository: Path, args: tuple[str, ...]) -> bytes:
    result = subprocess.run(  # noqa: S603 - Runs a fixed Git query against the selected repository.
        ["git", *args],  # noqa: S607 - Git is resolved from PATH as the repository tool.
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def git_bytes(git: Git, repository: Path, *args: str) -> bytes:
    return git(repository, tuple(args))


def git_text(git: Git, repository: Path, *args: str) -> str:
    return git_bytes(git, repository, *args).decode().strip()


def git_paths(git: Git, repository: Path, *args: str) -> set[str]:
    paths = set()
    for raw in git_bytes(git, repository, *args).split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        if not safe_relative(path):
            raise ValueError(f"unsafe git path: {path}")
        paths.add(path)
    return paths


def _read_cache(path: Path, repository: Path, knowledge: Path) -> Cache | None:
    try:
        file = json.loads(path.read_text())
        cache_value = file["cache"]
        cache_bytes = _serialize_cache_value(cache_value)
        if blob_hash(cache_bytes) != file["seal"]:
            return None
        cache = Cache(
            **{
                **cache_value,
                "domains": [Domain(**domain) for domain in cache_value["domains"]],
            }
        )
        if (
            cache.version != CACHE_VERSION
            or cache.repository != str(repository)
            or cache.knowledge != str(knowledge)
        ):
            return None
    except OSError, ValueError, TypeError, KeyError, json.JSONDecodeError:
        return None
    else:
        return cache


def write_cache(path: Path, cache: Cache) -> None:
    value = asdict(cache)
    for key in ("paths", "spec_hashes", "acknowledged_architecture_paths"):
        value[key] = dict(sorted(value[key].items()))
    raw = _serialize_cache_value(value)
    sealed = {"cache": value, "seal": blob_hash(raw)}
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(sealed, separators=(",", ":"), ensure_ascii=False))
    temporary.replace(path)


def _serialize_cache_value(value: dict) -> bytes:
    ordered = dict(value)
    for key in ("paths", "spec_hashes", "acknowledged_architecture_paths"):
        if isinstance(ordered.get(key), dict):
            ordered[key] = dict(sorted(ordered[key].items()))
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False).encode()
