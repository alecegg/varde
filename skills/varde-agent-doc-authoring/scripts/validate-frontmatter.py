# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Validate SKILL.md frontmatter against the agentskills.io spec.

Usage:
  uv run scripts/validate-frontmatter.py <path>...
  uv run scripts/validate-frontmatter.py ~/.claude/skills/*
  uv run scripts/validate-frontmatter.py .                    # current skill dir
  uv run scripts/validate-frontmatter.py --json <path>...     # machine-readable

Each <path> may be a skill directory (containing SKILL.md), a SKILL.md file
directly, or a directory of skill directories (e.g. an installed skills root
like ~/.pi/agent/skills) — the script auto-detects and recurses one level
when a path itself has no SKILL.md but its children do.

Checks:
  - Frontmatter is present and is valid YAML (catches unquoted `: ` inside
    plain scalars, the #1 real-world cause of silent install breakage).
  - name: required, <=64 chars, lowercase unicode alphanumeric + hyphens,
    no leading/trailing hyphen, no `--`, matches the parent directory name.
  - description: required, non-empty, <=1024 chars.
  - compatibility: optional, <=500 chars.
  - metadata: optional, must be a string->string map.
  - allowed-tools: optional, must be a string.
  - Unknown top-level frontmatter keys are reported as warnings, not errors.
  - SKILL.md body warns past ~500 lines (soft budget from the spec).

Exit codes: 0 all skills passed, 1 one or more skills failed, 2 usage error.
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "error: pyyaml is required — run this script with `uv run` so inline "
        "dependencies install automatically (see script header).",
        file=sys.stderr,
    )
    sys.exit(2)

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KNOWN_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
BODY_LINE_BUDGET = 500


def find_skill_md_files(path: Path):
    """Return SKILL.md files under `path`: itself, its skill dir, or one level of children."""
    if path.is_file() and path.name == "SKILL.md":
        return [path]
    if path.is_dir():
        direct = path / "SKILL.md"
        if direct.is_file():
            return [direct]
        # Not a skill dir itself — check immediate children (e.g. an installed skills root).
        found = []
        for child in sorted(path.iterdir()):
            candidate = child / "SKILL.md"
            if candidate.is_file():
                found.append(candidate)
        return found
    return []


def validate_skill(skill_md: Path) -> dict:
    errors = []
    warnings = []
    skill_dir = skill_md.parent
    text = skill_md.read_text(encoding="utf-8")

    match = FRONTMATTER_RE.match(text)
    if not match:
        errors.append("no `---`-delimited YAML frontmatter block found at the top of the file")
        return {"path": str(skill_md), "errors": errors, "warnings": warnings, "ok": False}

    raw_frontmatter = match.group(1)
    try:
        frontmatter = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as exc:
        errors.append(f"frontmatter is not valid YAML: {exc}")
        return {"path": str(skill_md), "errors": errors, "warnings": warnings, "ok": False}

    if not isinstance(frontmatter, dict):
        errors.append("frontmatter must be a YAML mapping (key: value pairs)")
        return {"path": str(skill_md), "errors": errors, "warnings": warnings, "ok": False}

    # name
    name = frontmatter.get("name")
    if not name:
        errors.append("missing required field `name`")
    elif not isinstance(name, str):
        errors.append(f"`name` must be a string, got {type(name).__name__}")
    else:
        if len(name) > 64:
            errors.append(f"`name` is {len(name)} chars, max is 64")
        if not NAME_RE.match(name):
            errors.append(
                f"`name` {name!r} must be lowercase alphanumeric + hyphens only, "
                "no leading/trailing hyphen, no consecutive hyphens"
            )
        if name != skill_dir.name:
            errors.append(f"`name` {name!r} must match parent directory name {skill_dir.name!r}")

    # description
    description = frontmatter.get("description")
    if not description:
        errors.append("missing required field `description`")
    elif not isinstance(description, str):
        errors.append(f"`description` must be a string, got {type(description).__name__}")
    elif len(description) > 1024:
        errors.append(f"`description` is {len(description)} chars, max is 1024")

    # compatibility
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str):
            errors.append(f"`compatibility` must be a string, got {type(compatibility).__name__}")
        elif len(compatibility) > 500:
            errors.append(f"`compatibility` is {len(compatibility)} chars, max is 500")

    # metadata
    metadata = frontmatter.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()
        ):
            errors.append("`metadata` must be a map of string keys to string values")

    # allowed-tools
    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append(f"`allowed-tools` must be a string, got {type(allowed_tools).__name__}")

    # unknown fields
    unknown = set(frontmatter.keys()) - KNOWN_FIELDS
    for key in sorted(unknown):
        warnings.append(f"unrecognized frontmatter field `{key}` (client-specific fields are fine)")

    # body size
    body_lines = text[match.end():].count("\n") + 1
    if body_lines > BODY_LINE_BUDGET:
        warnings.append(
            f"SKILL.md body is ~{body_lines} lines, over the {BODY_LINE_BUDGET}-line soft budget "
            "— consider moving detail into references/, assets/, or scripts/"
        )

    return {"path": str(skill_md), "errors": errors, "warnings": warnings, "ok": not errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="skill dir(s), SKILL.md file(s), or a dir of skill dirs")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON to stdout")
    args = parser.parse_args()

    all_skill_files = []
    for raw_path in args.paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            print(f"error: path not found: {path}", file=sys.stderr)
            sys.exit(2)
        found = find_skill_md_files(path)
        if not found:
            print(f"error: no SKILL.md found at or under {path}", file=sys.stderr)
            sys.exit(2)
        all_skill_files.extend(found)

    results = [validate_skill(f) for f in all_skill_files]
    any_failed = any(not r["ok"] for r in results)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "OK  " if r["ok"] else "FAIL"
            print(f"{status}  {r['path']}")
            for err in r["errors"]:
                print(f"      error:   {err}")
            for warn in r["warnings"]:
                print(f"      warning: {warn}")

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
