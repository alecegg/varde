#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_WORKING="$(mktemp -d "${TMPDIR:-/tmp}/varde-memory-boundary.XXXXXX")"
TEMP_WORKING="$(cd "$TEMP_WORKING" && pwd -P)"
trap 'rm -rf "$TEMP_WORKING"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_ignored() {
  git -C "$ROOT_DIR" check-ignore -q "$1" || fail "$1 is not ignored"
}

assert_trackable() {
  if git -C "$ROOT_DIR" check-ignore -q "$1"; then
    fail "$1 is ignored"
  fi
}

knowledge_hash() {
  find "$ROOT_DIR/memory-bank/knowledge" -type f -exec shasum {} \; |
    LC_ALL=C sort |
    shasum |
    awk '{print $1}'
}

assert_trackable memory-bank/knowledge/reference/example.md
assert_trackable memory-bank/config/type-config/plan.md
assert_ignored memory-bank/working/plans/example/plan.md
assert_ignored memory-bank/working/friction/example.md

before="$(knowledge_hash)"
printf 'local evidence\n' >"$TEMP_WORKING/evidence.md"
after="$(knowledge_hash)"
[ "$before" = "$after" ] || fail "working writes changed project knowledge"

# Resolve an isolated working store. A fresh checkout's default working path
# need not exist until the first write, so do not require it to pre-exist.
configured="$(cd "$ROOT_DIR" && VARDE_WORKING_DIR="$TEMP_WORKING" varde-workflow paths --json |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["working"])')"
[ "$configured" = "$TEMP_WORKING" ] || fail "configured working store did not resolve to the fixture"

if find "$ROOT_DIR/clis/code" "$ROOT_DIR/clis/workflow" "$ROOT_DIR/skills" "$ROOT_DIR/agents" "$ROOT_DIR/clis/toz" "$ROOT_DIR/clis/learn" \
  -name memory-bank -type d -print | grep -q .; then
  fail "module memory-bank remains"
fi

echo "memory boundary tests passed"
