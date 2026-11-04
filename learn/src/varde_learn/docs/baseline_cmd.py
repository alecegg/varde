"""``varde learn measure <skill> baseline``: manifest, changelog and git tags."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from importlib.metadata import entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from varde_core import skill_props

from .baseline import SkillStatus, diff_size, sha256_text, skill_status
from .flow.scan import text_tokens

UNPOINTED_FILE = "core/how-unpointed.txt"
_POINTER = re.compile(r"^\s*(?:[-*]\s+)?how:\s+([a-z0-9-]+)\s+-\s", re.MULTILINE)


class BaselineError(ValueError):
    """Unreadable or missing baseline input."""


def provider_packages() -> list[Traversable]:
    """The package root of every installed ``varde.skills`` provider."""
    return [files(point.value) for point in entry_points(group="varde.skills")]


def source_packages(repo: Path) -> list[Path]:
    """Package dirs (``<module>/src/<pkg>``) of a checkout holding skills or how."""
    return [
        package
        for package in sorted(repo.glob("*/src/*"))
        if (package / "skills").is_dir() or (package / "how").is_dir()
    ]


def find_manifest(baselines: Path) -> Path:
    """``<dir>/MANIFEST.json``, else the nested one with the top index."""
    direct = baselines / "MANIFEST.json"
    if direct.is_file():
        return direct
    nested = sorted(baselines.glob("*/MANIFEST.json")) if baselines.is_dir() else []
    if not nested:
        raise BaselineError(f"no MANIFEST.json under {baselines}")
    return max(nested, key=_manifest_rank)


def _manifest_rank(path: Path) -> tuple[int, str]:
    """Highest ``generations[].index``; unreadable manifests rank lowest."""
    try:
        generations = read_json(path).get("generations") or []
        indexes = [
            g["index"]
            for g in generations
            if isinstance(g, dict) and isinstance(g.get("index"), int)
        ]
    except BaselineError, TypeError:
        return (-1, path.parent.name)
    return (max(indexes, default=-1), path.parent.name)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineError(f"{path}: {error}") from error
    if not isinstance(data, dict):
        raise BaselineError(f"{path}: not a JSON object")
    return data


def read_changelog(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    lines = []
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            lines.append(json.loads(text))
        except json.JSONDecodeError as error:
            raise BaselineError(f"{path}:{number}: {error}") from error
    return lines


def _walk(node: Traversable, prefix: str = ""):
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        if child.name == "__pycache__":
            continue
        if child.is_dir():
            yield from _walk(child, f"{prefix}{child.name}/")
        else:
            yield f"{prefix}{child.name}", child


def current_files(packages: Sequence[Traversable]) -> dict[str, tuple[str, str]]:
    """Map ref to (sha256, text) for every installed skill file and how topic."""
    found: dict[str, tuple[str, str]] = {}
    for package in packages:
        skills = package / "skills"
        if skills.is_dir():
            for rel, node in _walk(skills):
                if not skill_props.is_hashed_path(rel.partition("/")[2]):
                    continue
                found[rel] = (sha256_text(node.read_bytes()), node.read_text("utf-8"))
        how = package / "how"
        if how.is_dir():
            for rel, node in _walk(how):
                if rel.endswith(".md"):
                    found[f"how/{rel.removesuffix('.md')}"] = (
                        sha256_text(node.read_bytes()),
                        node.read_text("utf-8"),
                    )
    return found


def _git(repo: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def head_commit(repo: Path) -> str | None:
    return _git(repo, "rev-parse", "HEAD")


def tag_commit(repo: Path, tag: str | None) -> str | None:
    if not tag:
        return None
    return _git(repo, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}")


def commit_touches(repo: Path, commit: str, ref: str) -> bool:
    """Whether ``commit`` changed the repository file behind ``ref``."""
    names = _git(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit
    )
    if names is None:
        return False
    suffix = ref.removeprefix("how/") + ".md" if ref.startswith("how/") else ref
    wanted = f"how/{suffix}" if ref.startswith("how/") else f"skills/{suffix}"
    return any(
        name.endswith(f"/{wanted}") or name == wanted for name in names.splitlines()
    )


def generation_dirs(manifest_path: Path, gen: str) -> list[Path]:
    """Directories that may hold ``slim/`` for ``gen``, in read order."""
    parent = manifest_path.parent
    return [parent.parent / gen, parent / gen, parent]


def baseline_text(manifest_path: Path, gen: str, ref: str) -> str | None:
    """The slim copy of ``ref``.

    Skills sit at ``slim/<skill>/<path>``; topics at
    ``slim/how/[<module>/]<skill>/<step>.md``.
    """
    for root in generation_dirs(manifest_path, gen):
        slim = root / "slim"
        if ref.startswith("how/"):
            rel = ref.removeprefix("how/") + ".md"
            matches = [slim / "how" / rel, *sorted(slim.glob(f"how/*/{rel}"))]
        else:
            matches = [slim / ref]
        for path in matches:
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return None


def _with_diff(status: SkillStatus, manifest_path: Path, texts: dict[str, str]) -> None:
    if status.baseline is None:
        return
    totals = {"lines_added": 0, "lines_removed": 0, "tokens": 0}
    for change in status.changes:
        ref = change["ref"]
        old = (
            ""
            if change["change"] == "added"
            else baseline_text(manifest_path, status.baseline["gen"], ref)
        )
        if old is None:
            status.diff = None
            return
        size = diff_size(old, texts.get(ref, ""), text_tokens)
        for key in totals:
            totals[key] += size[key]
    status.diff = totals


def layout_tree(own: dict[str, str], name: str, texts: dict[str, str]) -> dict:
    """Hashed files of one skill in synced layout from its current refs and texts."""
    tree: dict[str, bytes] = {}
    for ref in own:
        if ref.startswith(f"how/{name}/"):
            rel = f"how/{ref.removeprefix(f'how/{name}/')}.md"
        else:
            rel = ref.removeprefix(f"{name}/")
        if rel.startswith("how/") or skill_props.is_hashed_path(rel):
            tree[rel] = texts[ref].encode("utf-8")
    return tree


def tree_matches(entry: dict, tree: dict[str, bytes]) -> bool | None:
    """Whether the tree hash equals the entry's ``tree_hash``; None if unrecorded."""
    expected = entry.get("tree_hash")
    return skill_props.tree_hash(tree) == expected if expected else None


def statuses(
    baselines: Path, repo: Path, skill: str | None, packages: Sequence[Traversable]
) -> list[SkillStatus]:
    manifest_path = find_manifest(baselines)
    manifest = read_json(manifest_path)
    changelog = read_changelog(manifest_path.parent / "changelog.jsonl")
    skills = manifest.get("skills")
    if not isinstance(skills, dict):
        raise BaselineError(f"{manifest_path}: no skills object")
    if skill is not None and skill not in skills:
        raise BaselineError(
            f"unknown skill '{skill}'; valid skills: {', '.join(sorted(skills))}"
        )
    current = current_files(packages)
    result = []
    for name in [skill] if skill else sorted(skills):
        own = {
            ref: sha
            for ref, (sha, _) in current.items()
            if ref.startswith((f"{name}/", f"how/{name}/"))
        }
        status = skill_status(
            name, skills[name], changelog, own, lambda c, r: commit_touches(repo, c, r)
        )
        texts = {ref: current[ref][1] for ref in own}
        _with_diff(status, manifest_path, texts)
        if status.baseline is not None:
            newest = skills[name]["baselines"][-1]
            status.tree_hash_match = tree_matches(newest, layout_tree(own, name, texts))
        if status.baseline is not None:
            status.baseline["tag_commit"] = tag_commit(repo, status.baseline["tag"])
        if status.original is not None:
            status.original["tag_commit"] = tag_commit(repo, status.original["tag"])
        result.append(status)
    return result


def render_text(rows: list[SkillStatus]) -> str:
    lines = []
    for row in rows:
        base = row.baseline
        orig = row.original
        label = f"{base['gen']} ({base['tag']})" if base else "none"
        origin = orig["tag"] if orig else "none"
        drift = "n/a" if row.drift is None else ("DRIFT" if row.drift else "clean")
        match = {None: "n/a", True: "match", False: "MISMATCH"}[row.tree_hash_match]
        lines.append(
            f"{row.skill}: baseline {label}; original {origin}; {drift}; "
            f"tree hash {match}"
        )
        if row.diff:
            d = row.diff
            lines.append(
                f"  diff: +{d['lines_added']} -{d['lines_removed']} lines, "
                f"{d['tokens']:+d} tokens"
            )
        lines.extend(
            f"  gap-fill {f['fill']} {f['step'] or f['path']}: "
            f"+{f['tokens_added']} tokens"
            for f in row.fills
        )
        lines.extend(
            f"  {c['change']} {c['ref']}: "
            + (f"explained by {c['fill']}" if c["fill"] else "no changelog line")
            for c in row.changes
        )
    return "\n".join(lines)


def failed(rows: list[SkillStatus]) -> bool:
    """Whether any skill drifts from, or does not hash-match, its baseline."""
    return any(row.drift or row.tree_hash_match is False for row in rows)


def record_baseline(
    baselines: Path, repo: Path, skill: str, gen: str, meta: dict[str, object]
) -> dict[str, object]:
    """Append a baseline entry of ``skill`` built from the checkout at ``repo``.

    Writes ``files``, ``how`` and ``tree_hash`` into MANIFEST.json and the
    ``slim/`` copy under the generation directory. Returns the entry.
    """
    from varde_learn.loop.improve import baseline_store as store

    manifest_path = find_manifest(baselines)
    manifest = read_json(manifest_path)
    skills = manifest.setdefault("skills", {})
    recorded = skills.get(skill, {}).get("baselines", [])
    if any(entry.get("gen") == gen for entry in recorded):
        raise BaselineError(
            f"{skill} already has a baseline '{gen}' in {manifest_path}"
        )
    skill_dir, how_dir = _source_dirs(repo, skill)
    tree = store.layout_tree(skill_dir, how_dir)
    all_files = store.source_files(skill_dir)
    for path, data in tree.items():
        if path.startswith("how/"):
            all_files[path] = data
    entry = store.build_entry(skill, gen, tree, all_files, meta)
    skills.setdefault(skill, {}).setdefault("baselines", []).append(entry)
    nested = manifest_path.parent != baselines
    generation = generation_dirs(manifest_path, gen)[0 if nested else 1]
    store.write_slim(generation, skill, store.source_files(skill_dir), tree)
    list_unpointed(repo, skill, skill_dir, entry)
    staged = manifest_path.with_name(f".{manifest_path.name}.tmp")
    staged.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    staged.replace(manifest_path)
    return entry


def list_unpointed(repo: Path, skill: str, skill_dir: Path, entry: dict) -> None:
    """Add the entry's topics that SKILL.md does not point at to the repo list.

    The list is ``core/how-unpointed.txt`` (``how/<skill>/<step>`` per line),
    read by ``check-refs.sh``; a checkout without ``core/`` has none.
    """
    listing = repo / UNPOINTED_FILE
    if not listing.parent.is_dir():
        return
    pointed = set(_POINTER.findall((skill_dir / "SKILL.md").read_text("utf-8")))
    found = {
        f"how/{skill}/{step}" for step in entry.get("how", {}) if step not in pointed
    }
    known = set(listing.read_text("utf-8").split()) if listing.is_file() else set()
    if found - known:
        listing.write_text(
            "".join(f"{line}\n" for line in sorted(known | found)), "utf-8"
        )


def _source_dirs(repo: Path, skill: str) -> tuple[Path, Path | None]:
    for package in source_packages(repo):
        skill_dir = package / "skills" / skill
        if (skill_dir / "SKILL.md").is_file():
            how = package / "how" / skill
            return skill_dir, how if how.is_dir() else None
    raise BaselineError(f"no skill '{skill}' with SKILL.md under {repo}")
