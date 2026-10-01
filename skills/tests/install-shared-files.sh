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

"$SKILLS_DIR/install.sh" -f -d "$TEST_ROOT" >/dev/null

checks=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  rel_path="${line%% *}"
  read -r -a skills <<< "${line#* }"
  for skill in "${skills[@]}"; do
    installed="$TEST_ROOT/$skill/$rel_path"
    shared="$SKILLS_DIR/shared/$rel_path"
    [ -f "$installed" ] || fail "$skill is missing installed $rel_path"
    cmp -s "$installed" "$shared" || fail "$skill's $rel_path differs from skills/shared/$rel_path"
    checks=$((checks + 1))
  done
done < "$SKILLS_DIR/shared/MANIFEST"

[ "$checks" -gt 0 ] || fail "skills/shared/MANIFEST listed no files"

echo "install-shared-files: $checks installed copies match skills/shared/."
