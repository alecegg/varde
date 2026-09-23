#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-agent-generation.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

"$AGENTS_DIR/generate.py" --check

for harness in claude codex opencode; do
  destination="$TEST_ROOT/install-$harness"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$destination" -f >/dev/null
  case "$harness" in
    claude) variant="claude.md"; extension="md" ;;
    codex) variant="codex.toml"; extension="toml" ;;
    opencode) variant="opencode.md"; extension="md" ;;
  esac
  for profile in executor explore plan review; do
    cmp "$AGENTS_DIR/$profile/$variant" "$destination/$profile.$extension" ||
      fail "$harness installer changed generated $profile output"
  done
done

drift_root="$TEST_ROOT/drift"
mkdir -p "$drift_root"
for profile in executor explore plan review; do
  cp -R "$AGENTS_DIR/$profile" "$drift_root/$profile"
done
printf '\n# manual drift\n' >>"$drift_root/plan/codex.toml"

set +e
drift_output="$("$AGENTS_DIR/generate.py" --check --output-root "$drift_root" 2>&1)"
drift_status=$?
set -e
[ "$drift_status" -eq 1 ] || fail "modified adapter passed verification"
printf '%s\n' "$drift_output" | grep -F "stale: plan/codex.toml" >/dev/null ||
  fail "drift output omitted exact changed path"

echo "Generated adapter and installer tests passed."
