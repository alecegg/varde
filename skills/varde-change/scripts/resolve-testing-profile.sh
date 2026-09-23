#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <user|none> <repository|none> <decomposition-profile>" >&2
  echo "  user: require, waive, or none" >&2
  echo "  repository: require, exception, or none" >&2
}

if [ "$#" -ne 3 ]; then
  usage
  exit 2
fi

user_directive="$1"
repository_policy="$2"
decomposition_profile="$3"

case "$user_directive" in
  none|require|waive) ;;
  *) usage; exit 2 ;;
esac

case "$repository_policy" in
  none|require|exception) ;;
  *) usage; exit 2 ;;
esac

case "$decomposition_profile" in
  tdd|regression|characterization|smoke|not-applicable) ;;
  *) usage; exit 2 ;;
esac

if [ "$user_directive" = require ]; then
  printf '%s\n' 'profile=tdd; profile_source=user; strict_tdd=required'
  exit 0
fi

if [ "$user_directive" = waive ]; then
  printf 'profile=%s; profile_source=user; strict_tdd=waived\n' \
    "$decomposition_profile"
  exit 0
fi

case "$repository_policy" in
  require)
    printf '%s\n' 'profile=tdd; profile_source=repository; strict_tdd=required'
    ;;
  exception)
    printf '%s\n' 'profile=not-applicable; profile_source=exception; strict_tdd=exception'
    ;;
  none)
    printf 'profile=%s; profile_source=decomposition; strict_tdd=not-required\n' \
      "$decomposition_profile"
    ;;
esac
