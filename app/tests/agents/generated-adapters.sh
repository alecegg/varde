#!/usr/bin/env bash
set -euo pipefail
# Pin the OpenCode adapter generation so results never depend on the host.
export VARDE_AGENTS_OPENCODE_VERSION="${VARDE_AGENTS_OPENCODE_VERSION:-1.4.0}"

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../workflow/src/varde_workflow/agents" && pwd)"
GENERATOR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../app/scripts" && pwd)/generate.py"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-agent-generation.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

uv run --locked python "$GENERATOR" --check

drift_root="$TEST_ROOT/drift"
mkdir -p "$drift_root"
for profile in varde-builder varde-explorer varde-planner varde-reviewer; do
  cp -R "$AGENTS_DIR/$profile" "$drift_root/$profile"
done
printf '\n# manual drift\n' >>"$drift_root/varde-planner/codex.toml"

set +e
drift_output="$(uv run --locked python "$GENERATOR" --check --output-root "$drift_root" 2>&1)"
drift_status=$?
set -e
[ "$drift_status" -eq 1 ] || fail "modified adapter passed verification"
printf '%s\n' "$drift_output" | grep -F "stale: varde-planner/codex.toml" >/dev/null ||
  fail "drift output omitted exact changed path"

echo "Generated adapter checks passed."
