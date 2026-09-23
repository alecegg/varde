#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_WORKING="$ROOT_DIR/memory-bank/working/boundary-test.$$"
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
assert_trackable code-cli/memory-bank/knowledge/reference/example.md
assert_trackable workflow-cli/memory-bank/knowledge/reference/example.md
assert_trackable skills/memory-bank/knowledge/reference/example.md
assert_trackable agents/memory-bank/knowledge/reference/example.md

assert_ignored memory-bank/working/plans/example/plan.md
assert_ignored code-cli/memory-bank/working/plans/example/plan.md
assert_ignored workflow-cli/memory-bank/working/plans/example/plan.md
assert_ignored skills/memory-bank/working/plans/example/plan.md
assert_ignored agents/memory-bank/working/plans/example/plan.md
assert_ignored memory-bank/working/friction/example.md
assert_ignored memory-bank/friction/example.md

before="$(knowledge_hash)"
mkdir -p "$TEMP_WORKING"
printf 'local evidence\n' >"$TEMP_WORKING/evidence.md"
after="$(knowledge_hash)"

[ "$before" = "$after" ] || fail "working writes changed project knowledge"
git -C "$ROOT_DIR" check-ignore -q "${TEMP_WORKING#"$ROOT_DIR/"}/evidence.md" ||
  fail "working fixture appeared in repository state"

echo "memory boundary tests passed"
