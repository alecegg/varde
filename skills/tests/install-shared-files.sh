#!/usr/bin/env bash
# Every skill listed in skills/shared/MANIFEST for a shared file must receive
# that file, byte-identical to the shared copy, on a real install.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/install-shared-files.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if [[ -n "${VARDE_BIN:-}" ]]; then
  VARDE="$VARDE_BIN"
else
  (cd "$SKILLS_DIR/../clis" && cargo build --locked -q -p varde --bin varde --target-dir "$SKILLS_DIR/../clis/target")
  VARDE="$SKILLS_DIR/../clis/target/debug/varde"
fi

mkdir -p "$TEST_ROOT/home"
HOME="$TEST_ROOT/home" VARDE_CONFIG_DIR="$TEST_ROOT/home/config" VARDE_AGENTS_OPENCODE_VERSION=1 \
  "$VARDE" setup sync --skills-dir "$TEST_ROOT/skills" --agents-dir "$TEST_ROOT/agents" --harnesses none >/dev/null

checks=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  rel_path="${line%% *}"
  read -r -a skills <<< "${line#* }"
  for skill in "${skills[@]}"; do
    installed="$TEST_ROOT/skills/$skill/$rel_path"
    shared="$SKILLS_DIR/shared/$rel_path"
    [ -f "$installed" ] || fail "$skill is missing installed $rel_path"
    cmp -s "$installed" "$shared" || fail "$skill's $rel_path differs from skills/shared/$rel_path"
    checks=$((checks + 1))
  done
done < "$SKILLS_DIR/shared/MANIFEST"

[ "$checks" -gt 0 ] || fail "skills/shared/MANIFEST listed no files"

echo "install-shared-files: $checks installed copies match skills/shared/."
