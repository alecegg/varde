#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../../../core/tests/lib/repo.sh"
ROOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/varde-memory-boundary.XXXXXX")"
ROOT_DIR="$(cd "$ROOT_DIR" && pwd -P)"
TEMP_WORKING="$ROOT_DIR/working-fixture"
trap 'rm -rf "$ROOT_DIR"' EXIT

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

cp "$REPO_ROOT/.gitignore" "$ROOT_DIR/.gitignore"
mkdir -p "$ROOT_DIR/memory-bank/knowledge/reference" \
  "$ROOT_DIR/memory-bank/config/type-config" \
  "$ROOT_DIR/memory-bank/working/plans/example" \
  "$ROOT_DIR/memory-bank/working/friction" \
  "$ROOT_DIR/clis" "$ROOT_DIR/skills" "$ROOT_DIR/agents"
printf 'project knowledge\n' >"$ROOT_DIR/memory-bank/knowledge/reference/example.md"
printf 'plan config\n' >"$ROOT_DIR/memory-bank/config/type-config/plan.md"
printf 'session config\n' >"$ROOT_DIR/memory-bank/config/type-config/session-notes.md"
mkdir -p "$TEMP_WORKING"
git -C "$ROOT_DIR" init -q
git -C "$ROOT_DIR" add -f memory-bank/knowledge/reference/example.md \
  memory-bank/config/type-config/plan.md memory-bank/config/type-config/session-notes.md

assert_trackable memory-bank/knowledge/reference/example.md
assert_trackable memory-bank/config/type-config/plan.md
assert_trackable memory-bank/config/type-config/session-notes.md
assert_ignored memory-bank/working/plans/example/plan.md
assert_ignored memory-bank/working/friction/example.md

before="$(knowledge_hash)"
printf 'local evidence\n' >"$TEMP_WORKING/evidence.md"
after="$(knowledge_hash)"
[ "$before" = "$after" ] || fail "working writes changed project knowledge"

# Resolve an isolated working store. A fresh checkout's default working path
# need not exist until the first write, so do not require it to pre-exist.
configured="$(cd "$ROOT_DIR" && VARDE_WORKING_DIR="$TEMP_WORKING" varde setup paths --json |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["working"])')"
[ "$configured" = "$TEMP_WORKING" ] || fail "configured working store did not resolve to the fixture"

if find "$ROOT_DIR/clis" "$ROOT_DIR/skills" "$ROOT_DIR/agents" \
  -name memory-bank -type d -print | grep -q .; then
  fail "module memory-bank remains"
fi

echo "memory boundary tests passed"
