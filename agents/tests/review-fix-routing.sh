#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"

python3 - "$AGENTS_DIR" "$REPO_ROOT" <<'PY'
import json
import pathlib
import sys

agents = pathlib.Path(sys.argv[1])
repo = pathlib.Path(sys.argv[2])
manifest = json.loads((agents / "capabilities.json").read_text())
executor = next(profile for profile in manifest["profiles"] if profile["name"] == "varde-executor")
instructions = executor["instructions"].lower()
required = (
    "mode=build",
    "plan_context",
    "for standalone reviews, use `mode=standalone` with `review_dir` and `reporoot`; omit `plan_context`.",
    "never ask the user to triage",
    "return blank or unresolved findings to the parent",
    "the parent records",
    "for a parent-selected review fix, use `varde-change build` with a bounded task naming only the selected `finding_ids`",
)
for phrase in required:
    assert phrase in instructions, f"Executor manifest omits {phrase!r}"

for path in (
    agents / "varde-executor/claude.md",
    agents / "varde-executor/codex.toml",
    agents / "varde-executor/opencode.md",
):
    text = " ".join(path.read_text().lower().split())
    for phrase in required:
        assert phrase in text, f"{path.name} omits {phrase!r}"

fix = (repo / "skills/varde-review/references/fix.md").read_text().lower()
for phrase in (
    "plan-owned review",
    "standalone review folder",
    "the parent owns review orchestration and user triage",
    "the parent shows every unresolved blank finding",
    "do not perform human triage",
    "never prompts the user",
    "bounded build task",
):
    assert phrase in fix, f"fix.md omits {phrase!r}"

# fix-pass.md owns eligibility (review verdict batch 2 item 4).
fix_pass = " ".join((repo / "skills/varde-review/references/fix-pass.md").read_text().lower().split())
for phrase in (
    "any label with `disposition: fix`",
    "`label: auto-fix` with `disposition: blank` or `fix`",
    "send blank findings to parent triage",
):
    assert phrase in fix_pass, f"fix-pass.md omits {phrase!r}"

finish = (repo / "skills/varde-change/references/build-finish.md").read_text().lower()
for phrase in (
    "mode=build",
    "plan_context",
    "mode=standalone",
    "review_dir",
    "repoRoot",
    "finding_ids",
    "parent receives deferred findings",
):
    assert phrase.lower() in finish, f"build-finish.md omits {phrase!r}"

print("Review-fix parent-routing contract passed.")
PY
