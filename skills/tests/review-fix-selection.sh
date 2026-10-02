#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX_DOC="$REPO_ROOT/skills/varde-review/references/fix.md"
PASS_DOC="$REPO_ROOT/skills/varde-review/references/fix-pass.md"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -Fq "| Plan build (\`mode=build\`) | Any label with \`Disposition: fix\` | Send blank findings to parent triage without applying them; skip \`dismiss\`, \`action-item\`, and \`escalated\`. |" "$PASS_DOC" ||
  fail "fix-pass.md does not define plan-build eligibility"
grep -Fq "| Standalone (\`mode=standalone\`) | Only supplied \`finding_ids\` with \`Disposition: fix\` and decision evidence | Skip \`dismiss\`, \`action-item\`, and \`escalated\`" "$PASS_DOC" ||
  fail "fix-pass.md does not define standalone eligibility"
grep -Fq 'Check eligibility before doing' "$PASS_DOC" ||
  fail "fix-pass.md does not check eligibility first"
grep -Fq "| Plan build (\`mode=build\`) | Any label with \`Disposition: fix\` | Send blank findings to parent triage without applying them; skip \`dismiss\`, \`action-item\`, and \`escalated\`. |" "$PASS_DOC" ||
  fail "fix-pass.md does not keep blank plan-build findings in triage"

fixtures="$(
  cat <<'EOF'
standalone|auto-fix|blank|parent
standalone|auto-fix|fix|apply
standalone|auto-fix|dismiss|skip
standalone|auto-fix|action-item|skip
standalone|auto-fix|escalated|skip
build|auto-fix|blank|triage
build|auto-fix|fix|apply
build|auto-fix|dismiss|skip
build|auto-fix|action-item|skip
build|auto-fix|escalated|skip
standalone|triage|blank|parent
standalone|triage|fix|parent
build|triage|blank|triage
build|triage|fix|apply
EOF
)"

select_action() {
  local route="$1" label="$2" disposition="$3"
  case "$route:$label:$disposition" in
    standalone:auto-fix:fix|build:*:fix) printf 'apply' ;;
    build:*:blank) printf 'triage' ;;
    *:dismiss|*:action-item|*:escalated) printf 'skip' ;;
    standalone:*) printf 'parent' ;;
    *) fail "unknown fixture route or disposition: $route/$label/$disposition" ;;
  esac
}

count=0
while IFS='|' read -r route label disposition expected; do
  actual="$(select_action "$route" "$label" "$disposition")"
  [ "$actual" = "$expected" ] ||
    fail "$route/$label/$disposition selected $actual, expected $expected"
  count=$((count + 1))
done <<EOF
$fixtures
EOF

[ "$count" -eq 14 ] || fail "expected 14 selection fixtures, got $count"
for route in standalone build; do
  for disposition in blank fix dismiss action-item escalated; do
    printf '%s\n' "$fixtures" | awk -F '|' -v route="$route" -v disposition="$disposition" \
      '$1 == route && $3 == disposition { found = 1 } END { exit !found }' ||
      fail "missing $route fixture for disposition $disposition"
  done
done

echo "PASS: $count review-fix selection fixtures cover both routes and every disposition"
