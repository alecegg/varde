#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <task.md>" >&2
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  usage
  exit 2
fi

task_file="$1"

section() {
  local heading="$1"
  awk -v heading="$heading" '
    $0 == heading { in_section = 1; next }
    in_section && /^#### / { exit }
    in_section { print }
  ' "$task_file"
}

approach="$(section '#### Test approach')"
progress="$(section '#### Progress')"
profile="$(printf '%s\n' "$approach" | sed -n 's/^profile:[[:space:]]*//p')"
rationale="$(printf '%s\n' "$approach" | sed -n 's/^rationale:[[:space:]]*//p')"

strict_tdd_count="$(printf '%s\n' "$approach" | grep -c '^strict_tdd:' || true)"
[ "$strict_tdd_count" -le 1 ] ||
  fail "Test approach must contain at most one strict_tdd field"
strict_tdd="$(printf '%s\n' "$approach" | sed -n 's/^strict_tdd:[[:space:]]*//p')"
profile_source_count="$(printf '%s\n' "$approach" | grep -c '^profile_source:' || true)"
[ "$profile_source_count" -le 1 ] ||
  fail "Test approach must contain at most one profile_source field"
profile_source="$(printf '%s\n' "$approach" | sed -n 's/^profile_source:[[:space:]]*//p')"
exception_count="$(printf '%s\n' "$approach" | grep -c '^exception:' || true)"
[ "$exception_count" -le 1 ] ||
  fail "Test approach must contain at most one exception field"
exception_reason="$(printf '%s\n' "$approach" | sed -n 's/^exception:[[:space:]]*//p')"

case "$profile_source" in
  ''|user|repository|decomposition|exception) ;;
  *) fail "unsupported profile source: $profile_source" ;;
esac

case "$strict_tdd" in
  '')
    [ -z "$profile_source" ] ||
      fail "profile_source requires an explicit strict_tdd declaration"
    [ -z "$exception_reason" ] ||
      fail "exception requires an explicit strict_tdd declaration"
    ;;
  required)
    case "$profile_source" in
      user|repository) ;;
      *) fail "strict TDD requirement must name user or repository source" ;;
    esac
    ;;
  waived)
    [ "$profile_source" = user ] ||
      fail "strict TDD waiver must name user source"
    [ -z "$exception_reason" ] ||
      fail "strict TDD waiver cannot declare an exception"
    ;;
  not-required)
    [ "$profile_source" = decomposition ] ||
      fail "not-required strict TDD must name decomposition source"
    [ -z "$exception_reason" ] ||
      fail "not-required strict TDD cannot declare an exception"
    ;;
  exception)
    [ "$profile_source" = exception ] ||
      fail "strict TDD exception must name exception source"
    [ "$profile" = not-applicable ] ||
      fail "strict TDD exception must use not-applicable profile"
    [ -n "$exception_reason" ] ||
      fail "strict TDD exception reason is missing"
    ;;
  *) fail "unsupported strict_tdd declaration: $strict_tdd" ;;
esac

profile_count="$(printf '%s\n' "$approach" | grep -c '^profile:' || true)"
[ "$profile_count" -eq 1 ] ||
  fail "Test approach must contain one profile field"

case "$profile" in
  tdd) expected_checks='red,green,verify' ;;
  regression) expected_checks='reproduce,fix,verify' ;;
  characterization) expected_checks='characterize,verify' ;;
  smoke) expected_checks='smoke,verify' ;;
  not-applicable) expected_checks='not-applicable,structural' ;;
  *) fail "unsupported testing profile: ${profile:-missing}" ;;
esac

[ -n "$rationale" ] || fail "Test approach rationale is missing"

evidence_count="$(printf '%s\n' "$progress" | grep -c '^- evidence:' || true)"
[ "$evidence_count" -eq 1 ] ||
  fail "Progress must contain one evidence marker"

evidence="$(printf '%s\n' "$progress" | sed -n 's/^- evidence:[[:space:]]*//p')"
case "$evidence" in
  *"profile=$profile;"*) ;;
  *) fail "evidence profile does not match Test approach" ;;
esac
case "$evidence" in
  *"checks=$expected_checks;"*) ;;
  *) fail "evidence checks do not match profile $profile" ;;
esac
case "$evidence" in
  *"result=pass;"*) ;;
  *) fail "evidence result must be pass" ;;
esac
case "$evidence" in
  *"note="*)
    note="${evidence##*note=}"
    [ -n "$note" ] || fail "evidence note is missing"
    ;;
  *) fail "evidence note is missing" ;;
esac

if [ "$strict_tdd" = required ]; then
  [ "$profile" = tdd ] || fail "strict TDD requires profile=tdd"

  tdd_evidence="$(printf '%s\n' "$progress" | sed -n 's/^- tdd_evidence:[[:space:]]*//p')"
  tdd_evidence_count="$(printf '%s\n' "$tdd_evidence" | grep -c '^stage=' || true)"
  [ "$tdd_evidence_count" -eq 3 ] ||
    fail "strict TDD evidence must contain red,green,verify in order"

  red_stage="$(printf '%s\n' "$tdd_evidence" | sed -n '1p')"
  green_stage="$(printf '%s\n' "$tdd_evidence" | sed -n '2p')"
  verify_stage="$(printf '%s\n' "$tdd_evidence" | sed -n '3p')"
  case "$red_stage" in
    'stage=red; result=pass; note='*) ;;
    *) fail "strict TDD evidence must contain red,green,verify in order" ;;
  esac
  case "$green_stage" in
    'stage=green; result=pass; note='*) ;;
    *) fail "strict TDD evidence must contain red,green,verify in order" ;;
  esac
  case "$verify_stage" in
    'stage=verify; result=pass; note='*) ;;
    *) fail "strict TDD evidence must contain red,green,verify in order" ;;
  esac
  for stage in "$red_stage" "$green_stage" "$verify_stage"; do
    case "$stage" in
      *'note='*)
        note="${stage##*note=}"
        [ -n "$note" ] || fail "strict TDD evidence note is missing"
        ;;
    esac
  done
fi

printf 'Task evidence valid: profile=%s\n' "$profile"
