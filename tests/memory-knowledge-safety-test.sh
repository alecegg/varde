#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INVENTORY="$ROOT_DIR/memory-bank/knowledge/migration-review.yml"
TEMP_KNOWLEDGE="$(mktemp "$ROOT_DIR/memory-bank/knowledge/.safety-probe.XXXXXX")"
trap 'rm -f "$TEMP_KNOWLEDGE"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -f "$INVENTORY" ] || fail "missing knowledge migration review"
printf 'new project knowledge\n' >"$TEMP_KNOWLEDGE"

scope_count="$(sed -n 's/^  - path: //p' "$INVENTORY" | wc -l | tr -d ' ')"
[ "$scope_count" -gt 0 ] || fail "knowledge review has no scopes"

sed -n 's/^  - path: //p' "$INVENTORY" | while IFS= read -r scope; do
  reviewed_count="$(awk -v target="$scope" '
    $1 == "-" && $2 == "path:" { active = ($3 == target) }
    active && $1 == "reviewed_file_count:" { print $2; exit }
  ' "$INVENTORY")"
  reviewed_hash="$(awk -v target="$scope" '
    $1 == "-" && $2 == "path:" { active = ($3 == target) }
    active && $1 == "reviewed_tree_sha1:" { print $2; exit }
  ' "$INVENTORY")"
  disposition="$(awk -v target="$scope" '
    $1 == "-" && $2 == "path:" { active = ($3 == target) }
    active && $1 == "disposition:" { print $2; exit }
  ' "$INVENTORY")"
  classification="$(awk -v target="$scope" '
    $1 == "-" && $2 == "path:" { active = ($3 == target) }
    active && $1 == "classification:" { print $2; exit }
  ' "$INVENTORY")"
  [ -e "$ROOT_DIR/$scope" ] || fail "$scope does not exist"
  [ "$disposition" = track ] || fail "$scope lacks track disposition"
  [ "$classification" = project ] || fail "$scope lacks project classification"
  case "$reviewed_count" in
    ''|*[!0-9]*) fail "$scope lacks reviewed file count" ;;
  esac
  case "$reviewed_hash" in
    *[!0-9a-f]*|'') fail "$scope lacks reviewed tree hash" ;;
  esac
  [ "${#reviewed_hash}" -eq 40 ] || fail "$scope has invalid reviewed tree hash"
done

if find "$ROOT_DIR" \( -path '*/memory-bank/knowledge/*' \
  -o -path '*/memory-bank/config/*' \
  -o -path '*/memory-bank/README.md' \) -type f \
  -exec grep -EIH \
  '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|/Users/[^/[:space:]]+|/home/[^/[:space:]]+|file://)' {} +; then
  fail "knowledge contains a secret or machine-specific path"
fi

echo "memory knowledge safety tests passed"
