#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT_DIR/memory-bank/knowledge/workflow/active-surfaces.yml"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -f "$MANIFEST" ] || fail "missing active-surface manifest"
sed -n 's/^  - path: //p' "$MANIFEST" | LC_ALL=C sort >"$TEMP_DIR/declared"

while IFS= read -r surface; do
  [ -f "$ROOT_DIR/$surface" ] || fail "missing declared surface $surface"
  if grep -Eq 'command -v varde-docs|varde-docs (concept|lint|migrate|inspect|validate|recover)' "$ROOT_DIR/$surface"; then
    fail "$surface invokes the retired executable"
  fi
done <"$TEMP_DIR/declared"

rg -l 'command -v varde-workflow|varde-workflow (concept|lint|migrate|inspect|validate|recover)' \
  "$ROOT_DIR/skills" |
  sed "s|^$ROOT_DIR/||" |
  LC_ALL=C sort >"$TEMP_DIR/discovered"

while IFS= read -r surface; do
  grep -Fx "$surface" "$TEMP_DIR/declared" >/dev/null ||
    fail "undeclared workflow surface $surface"
done <"$TEMP_DIR/discovered"

grep -F 'Stop before CLI-owned mutations.' \
  "$ROOT_DIR/skills/varde-change/references/varde-workflow-cli.md" >/dev/null
grep -F 'Stop before CLI-owned mutations.' \
  "$ROOT_DIR/skills/varde-docs/references/varde-workflow-cli.md" >/dev/null
grep -F 'Stop before CLI-owned mutations.' \
  "$ROOT_DIR/skills/varde-knowledge/references/varde-workflow-cli.md" >/dev/null
grep -F 'stop before mutation.' \
  "$ROOT_DIR/skills/varde-knowledge/references/note.md" >/dev/null
grep -F 'stop before mutations' \
  "$ROOT_DIR/skills/varde-docs/references/spec.md" >/dev/null

echo "workflow active-surface tests passed"
