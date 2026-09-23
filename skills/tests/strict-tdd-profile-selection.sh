#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SELECTOR="$SKILLS_DIR/varde-change/scripts/resolve-testing-profile.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

run_case() {
  local name="$1"
  local user_directive="$2"
  local repository_policy="$3"
  local decomposition_profile="$4"
  local expected="$5"
  local actual
  actual="$($SELECTOR "$user_directive" "$repository_policy" "$decomposition_profile")" ||
    fail "$name case was rejected"
  [ "$actual" = "$expected" ] ||
    fail "$name resolved to '$actual', expected '$expected'"
}

run_invalid() {
  local name="$1"
  shift
  if "$SELECTOR" "$@" >/dev/null 2>&1; then
    fail "$name case was accepted"
  fi
}

test -x "$SELECTOR" || fail "profile selector is missing or not executable"

run_case user-requires require none regression \
  'profile=tdd; profile_source=user; strict_tdd=required'
run_case user-waives waive require regression \
  'profile=regression; profile_source=user; strict_tdd=waived'
run_case repository-requires none require smoke \
  'profile=tdd; profile_source=repository; strict_tdd=required'
run_case repository-exception none exception smoke \
  'profile=not-applicable; profile_source=exception; strict_tdd=exception'
run_case decomposition-default none none characterization \
  'profile=characterization; profile_source=decomposition; strict_tdd=not-required'

for profile in tdd regression characterization smoke not-applicable; do
  run_case "compatible-$profile" none none "$profile" \
    "profile=$profile; profile_source=decomposition; strict_tdd=not-required"
done

run_invalid bad-user unsupported none tdd
run_invalid bad-policy none unsupported tdd
run_invalid bad-profile none none unsupported

grep -F 'Direct user instructions outrank repository policy' \
  "$SKILLS_DIR/varde-change/references/build-decomposition.md" >/dev/null \
  || fail 'decomposition guidance omits user precedence'
grep -F 'resolve-testing-profile.sh' \
  "$SKILLS_DIR/varde-change/references/build.md" >/dev/null \
  || fail 'build guidance omits profile selector'

echo "Strict TDD profile selection fixtures passed."
