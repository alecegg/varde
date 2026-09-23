#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $(basename "$0") publish|deploy|rollback" >&2
  exit 2
fi

action="$1"
case "$action" in
  publish|deploy|rollback) ;;
  *)
    printf 'authorization=rejected\n'
    printf 'reason=Unsupported release mutation action: %s.\n' "$action"
    exit 2
    ;;
esac

if [ "${VARDE_RELEASE_AUTHORIZED:-}" != "1" ]; then
  printf 'authorization=absent\n'
  printf 'reason=Explicit authorization is required before %s; no provider command was run.\n' "$action"
  exit 1
fi

printf 'authorization=granted action=%s\n' "$action"
