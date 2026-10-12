#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import json
import pathlib
import shutil
import sys
import tempfile


agents = pathlib.Path(sys.argv[1])
variants = ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md")
contracts = {
    "varde-builder": (
        "require its location, ownership, checks, and constraints before editing",
        "do not plan, decompose, orchestrate, or create child tasks",
        "never mutate plan-wide state",
        "preserve unmanaged files and unrelated changes",
        "return unresolved findings to the parent",
        "spawn nothing except `varde-explorer`, and only as many as your brief allows",
        "report observed session-friction evidence to the caller",
        "caller owns capture",
        "friction:",
        "does not restrict writes required by the assigned task",
    ),
    "varde-reviewer": (
        "active review folder",
        "write only review artifacts",
        "never edit production source",
        "never split it yourself",
        "write findings immediately to `review.md`",
        "friction:",
    ),
    "varde-planner": (
        "do not implement the planned change",
        "do not create implementation task files",
        "require finalize's independent review",
        "finish only after the caller reports the verdict",
        "never substitute self-review",
    ),
    "varde-explorer": (
        "read-only structural navigation",
        "do not implement changes",
        "do not edit files or run destructive commands",
        "never spawn agents",
    ),
}

report_caps = {
    "varde-builder": "at most 10 lines",
    "varde-planner": "at most 12 lines",
    "varde-reviewer": "at most 8 lines",
    "varde-explorer": "at most 20 lines",
}
cap_detail = "details go in the persisted artifact"


def flatten(text):
    return " ".join(text.lower().split())


def failures(root):
    missing = []
    for role, phrases in contracts.items():
        for variant in variants:
            path = root / role / variant
            relative = f"{role}/{variant}"
            if not path.is_file():
                missing.append((relative, "generated role file exists"))
                continue
            text = flatten(path.read_text())
            missing.extend((relative, phrase) for phrase in phrases if phrase not in text)
    return missing


def fail(items):
    for path, phrase in items:
        print(f"FAIL: {path} is missing {phrase!r}", file=sys.stderr)
    raise SystemExit(1)


def cap_failures(manifest):
    # Report caps are read from the manifest; generated role files are refreshed
    # separately and are byte-compared against it by generate.py --check.
    instructions = {
        profile["name"]: flatten(profile.get("instructions", ""))
        for profile in manifest.get("profiles", [])
    }
    missing = []
    for role, cap in report_caps.items():
        text = instructions.get(role)
        if text is None:
            missing.append((role, "profile exists"))
            continue
        missing.extend(
            (role, phrase) for phrase in (cap, cap_detail) if phrase not in text
        )
    return missing


manifest = json.loads((agents / "capabilities.json").read_text())

current_failures = failures(agents)
if current_failures:
    fail(current_failures)

cap_items = cap_failures(manifest)
if cap_items:
    fail(cap_items)

# Prove every pinned boundary phrase is enforced by deleting it from a
# temporary copy of each generated role file, never from the checkout.
mutation_count = 0
with tempfile.TemporaryDirectory(prefix="varde-role-boundaries-") as temporary:
    copied = pathlib.Path(temporary)
    for role in contracts:
        shutil.copytree(agents / role, copied / role)

    for role, phrases in contracts.items():
        for variant in variants:
            path = copied / role / variant
            original = path.read_text()
            normalized = flatten(original)
            relative = f"{role}/{variant}"
            for phrase in phrases:
                path.write_text(normalized.replace(phrase, "[removed boundary contract]"))
                detected = failures(copied)
                path.write_text(original)
                if (relative, phrase) not in detected:
                    print(f"FAIL: mutation survived for {relative}: {phrase!r}", file=sys.stderr)
                    raise SystemExit(1)
                mutation_count += 1

    for role, cap in report_caps.items():
        mutated = json.loads(json.dumps(manifest))
        for profile in mutated["profiles"]:
            if profile["name"] == role:
                profile["instructions"] = flatten(profile["instructions"]).replace(
                    cap, "[removed report cap]"
                )
        detected = cap_failures(mutated)
        if (role, cap) not in detected:
            print(f"FAIL: report cap mutation survived for {role}: {cap!r}", file=sys.stderr)
            raise SystemExit(1)
        mutation_count += 1

print(f"Role boundary sentence contracts passed across {len(contracts) * len(variants)} files.")
print(f"Mutation checks detected {mutation_count} removed boundary and cap phrases.")
PY
