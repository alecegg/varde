#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Compute a low/high risk tier for a review scope from code and skill-doc signals.

Usage: risk-tier.py [--contract <file>] <scope-path>...

Prints `{"tier": "low"|"high", "signals": [...], "evidence": {...},
"tests_to_run": [...]}` to stdout. `tests_to_run` is always present: the
sorted repo-relative files under any `tests` directory (skipping `.git`,
`target`, `node_modules`, `.varde`, and any `fixtures` path component) whose
text names a scope path. A match is the repo-relative path, or the basename,
or `<parent-dir>/<basename>` for generic basenames (SKILL.md, FLOW.md,
README.md, AGENTS.md, CLAUDE.md, main.rs, lib.rs, mod.rs, __init__.py,
index.*); basename matches count only at a path boundary (preceding character
not in `[A-Za-z0-9._-]`). Tier is "high" when any of these trigger, by scope
kind. `dependent_outside_scope` and `skill_reach_external` are recorded in
`evidence` only and never raise the tier:

- Code scope (any path not classified as skill-doc): `varde-code
  blast_radius`, `nav_map`, and `clusters` per path. High when a scope file
  is marked foundational/entrypoint by `nav_map`, or scope spans more than
  one cluster.
- Skill-doc scope (a path under `skills/<skill>/...` or `skills/shared/...`,
  only when `skills/shared/MANIFEST` is a file; otherwise such paths are
  code):
  `skill-flow.py`'s reach, `skills/shared/MANIFEST`'s shared-file list,
  and `skills/tests/vendored-copies.sh`'s partial-section pins. High when the
  path is a file under `skills/shared/` or a skill's copy of one that
  `skills/shared/MANIFEST` lists for that skill (signal `shared_file`); or a
  byte-identical copy of a vendored-copies.sh-pinned file exists under
  another skill's `references/` (signal `vendored_copy_exists`). Reach
  leaving the owning skill (a route's `inline`, `unresolved`, or
  `dispatches`, or a `handoffs` entry that is not one of the skill's own
  files) is evidence `skill_reach_external` only. A bare directory scope
  that cannot resolve to one skill (e.g. `skills` itself) expands to every
  contained skill; if that finds none, or another scope path still can't be
  resolved, signal `scope_not_individually_classified` instead of a silent
  empty-signal low tier.
- `varde-code` missing, not indexed, or a failing query (only checked when
  the scope includes code paths): falls back to a `git grep` text check by
  file stem. A hit outside scope is evidence `dependent_outside_scope`
  (detail adds `"source": "text-fallback"`) only; high when more than one
  code path is in scope (`multi_file_scope_unverified`); `git grep` itself failing keeps
  `varde_code_unavailable` as a signal. Otherwise `varde_code_unavailable` is
  recorded in evidence only and the scope stays low.

`--contract` is accepted but unused here — contract-derived triggers
(`open_choices`, `shared_contracts`, missing verification checks) are
evaluated live by the CLI from the stored contract, not by this script.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def add_signal(signals, evidence, name, detail):
    if name not in signals:
        signals.append(name)
    evidence.setdefault(name, []).append(detail)


def classify(path, has_manifest):
    parts = Path(path).parts
    return "skill" if has_manifest and parts and parts[0] == "skills" else "code"


def run_varde_code(mode, payload):
    """Return parsed `data`, or None if varde-code is missing or the call fails."""
    if shutil.which("varde-code") is None:
        return None
    try:
        proc = subprocess.run(
            ["varde-code", mode, "--json", json.dumps(payload)],
            capture_output=True, text=True, timeout=120,
        )
        result = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if proc.returncode != 0 or not result.get("ok"):
        return None
    return result.get("data")


def code_signals(paths, repo_root, signals, evidence):
    unavailable = False
    scope = set(paths)

    for path in paths:
        dependents = run_varde_code("blast_radius", {"repoRoot": str(repo_root), "filePath": path})
        if dependents is None:
            unavailable = True
            continue
        outside = sorted(set(dependents) - scope)
        if outside:
            evidence.setdefault("dependent_outside_scope", []).append(
                {"path": path, "dependents": outside[:5]})

    nav = run_varde_code("nav_map", {"repoRoot": str(repo_root)})
    if nav is None:
        unavailable = True
    else:
        foundational = {f.get("file") for f in nav.get("foundational_files", [])}
        hit = sorted(scope & foundational)
        if hit:
            add_signal(signals, evidence, "foundational_file", {"paths": hit})

    clusters = run_varde_code("clusters", {"repoRoot": str(repo_root), "minSize": 1})
    if clusters is None:
        unavailable = True
    else:
        cluster_of = {f: c.get("id") for c in clusters.get("clusters", []) for f in c.get("files", [])}
        ids = {cluster_of.get(p, f"unresolved:{p}") for p in paths}
        if len(ids) > 1:
            add_signal(signals, evidence, "multi_cluster_scope",
                       {"paths": sorted(scope), "clusters": sorted(str(i) for i in ids)})

    if unavailable:
        text_fallback_signals(paths, repo_root, signals, evidence)


def text_fallback_signals(code_paths, repo_root, signals, evidence):
    """Fall back to a git grep text check when varde-code is unavailable.

    For each code path, search tracked files for its stem (`Path(path).stem`)
    with `git grep -l -w -F`, dropping hits that are themselves scope paths.
    A hit outside scope is recorded as `dependent_outside_scope` in `evidence`
    only (detail adds `"source": "text-fallback"`). More than one code path in scope signals
    `multi_file_scope_unverified`. If `git grep` itself
    fails (not a git checkout, git missing), `varde_code_unavailable` stays a
    signal, matching the varde-code-unavailable behavior. Otherwise
    `varde_code_unavailable` is recorded in `evidence` only, so a clean scope
    stays low tier.
    """
    scope = set(code_paths)
    for path in code_paths:
        stem = Path(path).stem
        try:
            proc = subprocess.run(
                ["git", "grep", "-l", "-w", "-F", "-e", stem],
                cwd=repo_root, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            add_signal(signals, evidence, "varde_code_unavailable", {"paths": code_paths})
            return
        if proc.returncode not in (0, 1):
            add_signal(signals, evidence, "varde_code_unavailable", {"paths": code_paths})
            return
        hits = sorted(set(proc.stdout.splitlines()) - scope)
        if hits:
            evidence.setdefault("dependent_outside_scope", []).append(
                {"path": path, "dependents": hits[:5], "source": "text-fallback"})

    if len(code_paths) > 1:
        add_signal(signals, evidence, "multi_file_scope_unverified", {"paths": code_paths})

    evidence.setdefault("varde_code_unavailable", []).append({"paths": code_paths})


def skill_flow_data(skill_dir, skill_flow_script):
    try:
        proc = subprocess.run(
            [sys.executable, "-B", str(skill_flow_script), "--json", str(skill_dir)],
            capture_output=True, text=True, timeout=120,
        )
        parsed = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if proc.returncode != 0 or not parsed:
        return None
    return parsed[0]


def reach_leaves_skill(flow, rel_path):
    own_files = flow.get("tokens", {})
    for route in flow.get("routes", []):
        reached = rel_path == "SKILL.md" or rel_path in route.get("files", [])
        if not reached:
            continue
        if route.get("inline") or route.get("unresolved") or route.get("dispatches"):
            return True
        if any(handoff not in own_files for handoff in route.get("handoffs", [])):
            return True
    return False


def vendored_manifest_names(vendored_manifest):
    if not vendored_manifest.is_file():
        return set()
    match = re.search(r"MANIFEST=\((.*?)\n\)", vendored_manifest.read_text(), re.S)
    if not match:
        return set()
    names = set()
    for entry in re.findall(r'"([^"]+)"', match.group(1)):
        names.update(entry.split(":", 1)[0].split("|"))
    return names


def shared_manifest_skills(shared_manifest):
    """Map each shared-file relative path to the skills install.sh copies it into."""
    mapping = {}
    if not shared_manifest.is_file():
        return mapping
    for line in shared_manifest.read_text().splitlines():
        rel, *skill_names = line.split()
        if rel:
            mapping[rel] = skill_names
    return mapping


def vendored_copy_elsewhere(target_file, name, skills_dir):
    if not target_file.is_file():
        return []
    target_bytes = target_file.read_bytes()
    matches = []
    for candidate in skills_dir.glob(f"*/references/{name}"):
        if candidate.resolve() == target_file.resolve():
            continue
        if candidate.is_file() and candidate.read_bytes() == target_bytes:
            matches.append(str(candidate.relative_to(skills_dir)))
    return matches


SKIP_DIRS = {".git", "target", "node_modules", ".varde"}
GENERIC_BASENAMES = {"SKILL.md", "FLOW.md", "README.md", "AGENTS.md", "CLAUDE.md",
                     "main.rs", "lib.rs", "mod.rs", "__init__.py"}


def is_generic(name):
    return name in GENERIC_BASENAMES or re.fullmatch(r"index\..+", name) is not None


def names_at_boundary(text, needle):
    pattern = r"(?<![A-Za-z0-9._-])" + re.escape(needle)
    return re.search(pattern, text) is not None


def test_files(repo_root):
    """Yield repo-relative files under any directory named `tests`."""
    stack = [repo_root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            rel_parts = child.relative_to(repo_root).parts
            if child.is_symlink() or any(p in SKIP_DIRS or p == "fixtures" for p in rel_parts):
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file() and "tests" in rel_parts[:-1]:
                yield child


def tests_naming_scope(paths, repo_root):
    needles = []
    for path in paths:
        posix = Path(path).as_posix()
        name = Path(path).name
        if is_generic(name):
            parent = Path(path).parent.name
            base = f"{parent}/{name}" if parent else name
        else:
            base = name
        needles.append((posix, base))
    hits = set()
    for candidate in test_files(repo_root):
        try:
            text = candidate.read_text(errors="replace")
        except OSError:
            continue
        if any(names_at_boundary(text, full) or names_at_boundary(text, base)
               for full, base in needles):
            hits.add(candidate.relative_to(repo_root).as_posix())
    return sorted(hits)


def skill_relative(path):
    parts = Path(path).parts
    if len(parts) < 2 or parts[0] != "skills":
        return None
    return Path(*parts[1:])


def skill_signals(paths, signals, evidence, skills_dir):
    skill_flow_script = skills_dir / "varde-agent-doc-authoring" / "scripts" / "skill-flow.py"
    tests_dir = skills_dir / "tests"
    manifest_names = vendored_manifest_names(tests_dir / "vendored-copies.sh")
    shared_files = shared_manifest_skills(skills_dir / "shared" / "MANIFEST")
    flow_cache = {}

    def evaluate(path, rel):
        skill_name = rel.parts[0]
        skill_dir = skills_dir / skill_name
        within = rel.relative_to(skill_name).as_posix() if len(rel.parts) > 1 else "SKILL.md"
        target_file = skills_dir / rel

        if (skill_dir / "SKILL.md").is_file():
            if skill_name not in flow_cache:
                flow_cache[skill_name] = skill_flow_data(skill_dir, skill_flow_script)
            flow = flow_cache[skill_name]
            if flow and reach_leaves_skill(flow, within):
                evidence.setdefault("skill_reach_external", []).append({"path": path})

        consumers = shared_files.get(within, [])
        if skill_name == "shared" or skill_name in consumers:
            add_signal(signals, evidence, "shared_file", {"path": path, "skills": consumers})

        name = target_file.name
        if name in manifest_names:
            copies = vendored_copy_elsewhere(target_file, name, skills_dir)
            if copies:
                add_signal(signals, evidence, "vendored_copy_exists", {"path": path, "copies": copies})

    for path in paths:
        rel = skill_relative(path)
        if rel is not None:
            evaluate(path, rel)
            continue

        # A directory that can't resolve to one skill (bare `skills`, today's
        # only case, since `classify` already requires parts[0] == "skills")
        # expands to every contained skill instead of silently producing no
        # signals (friction 16).
        contained = []
        if skills_dir.is_dir():
            contained = sorted(
                child.name
                for child in skills_dir.iterdir()
                if child.is_dir() and (child / "SKILL.md").is_file()
            )
        if contained:
            for skill_name in contained:
                evaluate(f"skills/{skill_name}", Path(skill_name))
        else:
            add_signal(signals, evidence, "scope_not_individually_classified", {"path": path})


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract")
    parser.add_argument("paths", nargs="+", metavar="scope-path")
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    signals, evidence = [], {}

    has_manifest = (repo_root / "skills" / "shared" / "MANIFEST").is_file()
    code_paths = [p for p in args.paths if classify(p, has_manifest) == "code"]
    skill_paths = [p for p in args.paths if classify(p, has_manifest) == "skill"]

    if code_paths:
        code_signals(code_paths, repo_root, signals, evidence)
    if skill_paths:
        skill_signals(skill_paths, signals, evidence, repo_root / "skills")

    tier = "high" if signals else "low"
    print(json.dumps({"tier": tier, "signals": signals, "evidence": evidence,
                      "tests_to_run": tests_naming_scope(args.paths, repo_root)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
