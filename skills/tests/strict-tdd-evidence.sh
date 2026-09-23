#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATOR="$SKILLS_DIR/varde-change/scripts/validate-task-evidence.sh"
FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

write_fixture() {
  local fixture="$1"
  local profile="$2"
  local strict_tdd="$3"
  local source="$4"
  local exception="$5"
  local evidence="$6"
  shift 6

  {
    cat <<EOF
---
type: task
status: done
---

Strict TDD fixture

#### Test approach

profile: $profile
rationale: Exercise strict evidence validation.
strict_tdd: $strict_tdd
profile_source: $source
EOF
    if [ -n "$exception" ]; then
      printf 'exception: %s\n' "$exception"
    fi
    printf '\n#### Progress\n\n'
    for marker in "$@"; do
      printf '%s\n' "$marker"
    done
    printf '%s\n' "$evidence"
  } > "$fixture"
}

assert_valid() {
  local name="$1"
  shift
  local fixture="$FIXTURE_DIR/$name.md"
  write_fixture "$fixture" "$@"
  "$VALIDATOR" "$fixture" >/dev/null || fail "$name fixture was rejected"
}

assert_invalid() {
  local name="$1"
  shift
  local fixture="$FIXTURE_DIR/$name.md"
  write_fixture "$fixture" "$@"
  if "$VALIDATOR" "$fixture" >/dev/null 2>&1; then
    fail "$name fixture was accepted"
  fi
}

strict_evidence=(
  '- tdd_evidence: stage=red; result=pass; note=failing assertion observed'
  '- tdd_evidence: stage=green; result=pass; note=implementation passes'
  '- tdd_evidence: stage=verify; result=pass; note=full checks pass'
)

assert_valid complete-tdd tdd required user "" \
  '- evidence: profile=tdd; checks=red,green,verify; result=pass; note=strict fixture passed' \
  "${strict_evidence[@]}"

assert_invalid missing-green tdd required user "" \
  '- evidence: profile=tdd; checks=red,green,verify; result=pass; note=missing green' \
  "${strict_evidence[0]}" "${strict_evidence[2]}"

assert_invalid missing-red tdd required user "" \
  '- evidence: profile=tdd; checks=red,green,verify; result=pass; note=missing red' \
  "${strict_evidence[1]}" "${strict_evidence[2]}"

assert_invalid missing-verify tdd required user "" \
  '- evidence: profile=tdd; checks=red,green,verify; result=pass; note=missing verify' \
  "${strict_evidence[0]}" "${strict_evidence[1]}"

assert_invalid reordered-tdd tdd required user "" \
  '- evidence: profile=tdd; checks=red,green,verify; result=pass; note=reordered stages' \
  "${strict_evidence[2]}" "${strict_evidence[0]}" "${strict_evidence[1]}"

assert_invalid strict-non-tdd smoke required user "" \
  '- evidence: profile=smoke; checks=smoke,verify; result=pass; note=strict fixture' \
  '- tdd_evidence: stage=red; result=pass; note=wrong profile'

assert_valid declared-exception not-applicable exception exception \
  'Generated content has no executable seam.' \
  '- evidence: profile=not-applicable; checks=not-applicable,structural; result=pass; note=declared exception'

assert_invalid undeclared-exception not-applicable exception decomposition \
  'Missing policy declaration.' \
  '- evidence: profile=not-applicable; checks=not-applicable,structural; result=pass; note=undeclared exception'

assert_invalid missing-exception-reason not-applicable exception exception "" \
  '- evidence: profile=not-applicable; checks=not-applicable,structural; result=pass; note=missing reason'

strict_failure_output=""
if strict_failure_output="$($VALIDATOR "$FIXTURE_DIR/missing-green.md" 2>&1)"; then
  fail 'strict evidence failure fixture was accepted'
fi
if ! grep -F 'red,green,verify' <<< "$strict_failure_output" >/dev/null; then
  fail 'strict evidence failure did not name red,green,verify'
fi

grep -F 'strict_tdd:' "$SKILLS_DIR/varde-change/assets/TASK-TEMPLATE.md" >/dev/null \
  || fail 'task template omits strict TDD fields'
grep -F 'profile_source:' "$SKILLS_DIR/varde-change/assets/TASK-TEMPLATE.md" >/dev/null \
  || fail 'task template omits profile source field'
grep -F 'tdd_evidence' "$SKILLS_DIR/varde-change/references/build-execution.md" >/dev/null \
  || fail 'build execution omits ordered TDD evidence'

echo "Strict TDD evidence fixtures passed."
