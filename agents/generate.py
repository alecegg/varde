#!/usr/bin/env python3
"""Generate committed assistant adapters from one capability manifest."""

from __future__ import annotations

import argparse
import filecmp
import json
import pathlib
import tempfile


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
VARIANTS = {
    "claude": "claude.md",
    "codex": "codex.toml",
    "opencode": "opencode.md",
}
OPENCODE_TOOLS = ("read", "write", "edit", "grep", "glob", "bash")
HARNESSES = ("claude", "codex", "opencode")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-root", type=pathlib.Path, default=SCRIPT_DIR)
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=SCRIPT_DIR / "capabilities.json",
    )
    parser.add_argument(
        "--templates",
        type=pathlib.Path,
        default=SCRIPT_DIR / "templates",
    )
    return parser.parse_args()


def load_manifest(path: pathlib.Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("capability manifest version must equal 1")
    skills = manifest.get("skills")
    if not isinstance(skills, list) or skills != sorted(set(skills)):
        raise ValueError("manifest skills must be sorted and unique")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("manifest requires profiles")
    validate_profiles(manifest, skills, profiles)
    return manifest


def validate_profiles(manifest: dict, skills: list, profiles: list) -> None:
    names = [profile.get("name") for profile in profiles]
    if len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("profile names must be present and unique")
    for profile in profiles:
        validate_profile(manifest, skills, profile)


def validate_profile(manifest: dict, skills: list, profile: dict) -> None:
    unknown = set(profile.get("skills", [])) - set(skills)
    if unknown:
        raise ValueError(f"{profile['name']} references unknown skills: {sorted(unknown)}")
    instructions = profile.get("instructions", "")
    validate_instructions(manifest, profile, instructions)
    models = profile.get("models")
    if not isinstance(models, dict) or set(models) != set(HARNESSES):
        raise ValueError(f"{profile['name']} must define models for every harness")
    for harness in HARNESSES:
        validate_model_policy(profile["name"], harness, models[harness])


def validate_instructions(manifest: dict, profile: dict, instructions: str) -> None:
    for skill in profile.get("skills", []):
        if skill not in instructions:
            raise ValueError(f"{profile['name']} instructions omit skill {skill}")
    for command_name in profile.get("uses_commands", []):
        command = manifest.get("commands", {}).get(command_name)
        if command is None:
            raise ValueError(f"{profile['name']} references unknown command {command_name}")
        if command not in instructions:
            raise ValueError(f"{profile['name']} instructions omit command {command}")
    if '"""' in instructions:
        raise ValueError(f"{profile['name']} instructions contain TOML delimiter")


def validate_model_policy(name: str, harness: str, policy: dict) -> None:
    if not isinstance(policy, dict) or not policy.get("model"):
        raise ValueError(f"{name} {harness} model is required")
    if not isinstance(policy.get("reasoning_efforts"), list):
        raise ValueError(f"{name} {harness} reasoning_efforts must be a list")
    supported = policy.get("reasoning_effort_supported")
    selected = policy.get("reasoning_effort")
    if not isinstance(supported, bool):
        raise ValueError(f"{name} {harness} reasoning support is required")
    if supported and selected not in policy["reasoning_efforts"]:
        raise ValueError(f"{name} {harness} selects an unsupported reasoning effort")
    if not supported and selected is not None:
        raise ValueError(f"{name} {harness} cannot select reasoning effort")


def load_templates(root: pathlib.Path) -> dict[str, str]:
    return {
        harness: (root / f"{filename}.tpl").read_text(encoding="utf-8")
        for harness, filename in VARIANTS.items()
    }


def context(profile: dict) -> dict[str, str]:
    codex = profile["models"]["codex"]
    sandbox = codex.get("sandbox_mode")
    claude = profile["models"]["claude"]
    opencode = profile["models"]["opencode"]
    enabled = set(profile["opencode_tools"])
    return {
        "name": profile["name"],
        "name_toml": json.dumps(profile["name"]),
        "description_yaml": json.dumps(profile["description"], ensure_ascii=False),
        "description_toml": json.dumps(profile["description"], ensure_ascii=False),
        "claude_model": json.dumps(claude["model"], ensure_ascii=False),
        "claude_tools": ", ".join(profile["claude_tools"]),
        "skills": ", ".join(profile["skills"]),
        "opencode_tools": "\n".join(
            f"  {tool}: {str(tool in enabled).lower()}" for tool in OPENCODE_TOOLS
        ),
        "model_toml": json.dumps(codex["model"]),
        "reasoning_toml": json.dumps(codex["reasoning_effort"]),
        "opencode_model": json.dumps(opencode["model"], ensure_ascii=False),
        "sandbox_line": f"sandbox_mode = {json.dumps(sandbox)}\n" if sandbox else "",
        "instructions": profile["instructions"].rstrip(),
    }


def render(template: str, values: dict[str, str]) -> str:
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("template contains an unresolved placeholder")
    return rendered.rstrip() + "\n"


def generate(manifest: dict, templates: dict[str, str], output: pathlib.Path) -> list[pathlib.Path]:
    written = []
    for profile in sorted(manifest["profiles"], key=lambda item: item["name"]):
        values = context(profile)
        directory = output / profile["name"]
        directory.mkdir(parents=True, exist_ok=True)
        for harness, filename in VARIANTS.items():
            path = directory / filename
            path.write_text(render(templates[harness], values), encoding="utf-8")
            written.append(path)
    return written


def generated_paths(root: pathlib.Path) -> set[pathlib.Path]:
    names = set(VARIANTS.values())
    return {
        path.relative_to(root)
        for path in root.glob("*/*")
        if path.is_file() and path.name in names
    }


def verify(manifest: dict, templates: dict[str, str], committed: pathlib.Path) -> int:
    with tempfile.TemporaryDirectory(prefix="varde-agents-") as temporary:
        expected_root = pathlib.Path(temporary)
        expected = generate(manifest, templates, expected_root)
        expected_paths = {path.relative_to(expected_root) for path in expected}
        committed_paths = generated_paths(committed)
        drift = []
        for relative in sorted(expected_paths | committed_paths):
            expected_path = expected_root / relative
            committed_path = committed / relative
            if not expected_path.exists():
                drift.append(f"unexpected: {relative}")
            elif not committed_path.exists():
                drift.append(f"missing: {relative}")
            elif not filecmp.cmp(expected_path, committed_path, shallow=False):
                drift.append(f"stale: {relative}")
        if drift:
            print("Generated adapter drift:")
            for item in drift:
                print(item)
            return 1
    print("Generated assistant adapters are current.")
    return 0


def main() -> int:
    args = arguments()
    manifest = load_manifest(args.manifest)
    templates = load_templates(args.templates)
    if args.check:
        return verify(manifest, templates, args.output_root)
    written = generate(manifest, templates, args.output_root)
    for path in written:
        print(path.relative_to(args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
