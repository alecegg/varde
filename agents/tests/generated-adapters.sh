#!/usr/bin/env bash
set -euo pipefail
# Pin the OpenCode adapter generation so results never depend on the host.
export VARDE_AGENTS_OPENCODE_VERSION="${VARDE_AGENTS_OPENCODE_VERSION:-1.4.0}"
OPENCODE_VARIANT=opencode.md
[ "${VARDE_AGENTS_OPENCODE_VERSION%%.*}" -lt 2 ] || OPENCODE_VARIANT=opencode-v2.md

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-agent-generation.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

"$AGENTS_DIR/generate.py" --check

drift_root="$TEST_ROOT/drift"
mkdir -p "$drift_root"
for profile in varde-builder varde-explorer varde-planner varde-reviewer; do
  cp -R "$AGENTS_DIR/$profile" "$drift_root/$profile"
done
printf '\n# manual drift\n' >>"$drift_root/varde-planner/codex.toml"

set +e
drift_output="$("$AGENTS_DIR/generate.py" --check --output-root "$drift_root" 2>&1)"
drift_status=$?
set -e
[ "$drift_status" -eq 1 ] || fail "modified adapter passed verification"
printf '%s\n' "$drift_output" | grep -F "stale: varde-planner/codex.toml" >/dev/null ||
  fail "drift output omitted exact changed path"

# Spawn rules: only varde-explorer may be spawned, and only where granted.
python3 - "$AGENTS_DIR" "$OPENCODE_VARIANT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
opencode_variant = sys.argv[2]
spawn_line = (
    "spawn nothing except `varde-explorer`, and only as many as your brief allows"
)


def text(profile, variant):
    return " ".join((root / profile / variant).read_text().lower().split())


def header(profile, variant):
    return (root / profile / variant).read_text().split("---", 2)[1]


for variant in ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md"):
    explorer = text("varde-explorer", variant)
    assert "never spawn agents" in explorer, variant
    assert "spawn nothing except" not in explorer, variant
    for profile in ("varde-planner", "varde-builder", "varde-reviewer"):
        body = text(profile, variant)
        assert spawn_line in body, (profile, variant)
        assert "without spawning or delegating" not in body, (profile, variant)
    planner = text("varde-planner", variant)
    assert "if this agent cannot delegate" not in planner, variant
    assert "return to the caller requesting it, and finish only after the caller reports the verdict; never substitute self-review" in planner, variant
    assert "do the task yourself" in text("varde-builder", variant), variant
    assert "wait for the verdict" not in planner and "wait at the gate" not in text("varde-builder", variant), variant
    reviewer = text("varde-reviewer", variant)
    assert "no agent tool" not in reviewer, variant
    assert "when the read is over budget, report back to the caller to split the review; never split it yourself" in reviewer, variant

for profile in ("varde-planner", "varde-builder", "varde-reviewer", "varde-explorer"):
    grants = profile != "varde-explorer"
    v1 = json.loads(next(l.removeprefix("permission: ") for l in header(profile, "opencode.md").splitlines() if l.startswith("permission: ")))
    v2 = json.loads(next(l.removeprefix("permissions: ") for l in header(profile, "opencode-v2.md").splitlines() if l.startswith("permissions: ")))
    subagent = [(r["resource"], r["effect"]) for r in v2 if r["action"] == "subagent"]
    if grants:
        assert v1["task"] == {"*": "deny", "varde-explorer": "allow"}, profile
        assert subagent == [("*", "deny"), ("varde-explorer", "allow")], profile
    else:
        assert v1["task"] == "deny", profile
        assert subagent == [("*", "deny")], profile
    claude_tools = next(l for l in (root / profile / "claude.md").read_text().splitlines() if l.startswith("tools:"))
    assert not {"Agent", "Task"} & {t.strip() for t in claude_tools.removeprefix("tools:").split(",")}, (profile, claude_tools)
    codex_lines = (root / profile / "codex.toml").read_text().splitlines()
    assert not [l for l in codex_lines if l.startswith("[") or l.split("=")[0].strip() in ("agents", "max_depth", "max_threads", "spawn")], profile
print("Spawn rule assertions passed.")
PY

echo "Generated adapter checks passed."
