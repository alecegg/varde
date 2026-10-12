#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX_DOC="$REPO_ROOT/skills/varde-review/references/fix.md"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -Fq 'holds every finding with a status: `open`, `fixed`, `deferred`,' "$FIX_DOC" ||
  fail "fix.md does not define the per-finding status set"
grep -Fq "Apply every fix that keeps the plan's intended" "$FIX_DOC" ||
  fail "fix.md does not apply only behaviour-preserving fixes"
grep -Fq 'Group the fixes that change intended behaviour' "$FIX_DOC" ||
  fail "fix.md does not group intended-behaviour changes for the user"
grep -Fq 'deferred store' "$FIX_DOC" ||
  fail "fix.md does not send deferred findings to the deferred store"
grep -Fq 'header-only re-check' "$FIX_DOC" ||
  fail "fix.md does not re-check non-behavioural fixes by header"
grep -Fq 'at most two repair rounds' "$FIX_DOC" ||
  fail "fix.md does not cap batch repair at two rounds"

fixtures="$(
  cat <<'EOF'
open|intended|apply
open|changed|ask
fixed|intended|skip
fixed|changed|skip
deferred|intended|skip
deferred|changed|skip
asked|intended|skip
asked|changed|skip
EOF
)"

select_action() {
  local status="$1" behaviour="$2"
  case "$status" in
    fixed|deferred|asked) printf 'skip' ;;
    open)
      case "$behaviour" in
        intended) printf 'apply' ;;
        changed) printf 'ask' ;;
        *) fail "unknown behaviour: $behaviour" ;;
      esac
      ;;
    *) fail "unknown status: $status" ;;
  esac
}

count=0
while IFS='|' read -r status behaviour expected; do
  actual="$(select_action "$status" "$behaviour")"
  [ "$actual" = "$expected" ] ||
    fail "$status/$behaviour selected $actual, expected $expected"
  count=$((count + 1))
done <<EOF
$fixtures
EOF

[ "$count" -eq 8 ] || fail "expected 8 selection fixtures, got $count"
for behaviour in intended changed; do
  printf '%s\n' "$fixtures" | awk -F '|' -v behaviour="$behaviour" \
    '$1 == "open" && $2 == behaviour { found = 1 } END { exit !found }' ||
    fail "missing open fixture for $behaviour behaviour"
done

echo "PASS: $count review-fix selection fixtures cover applies, asks and skips"
