#!/usr/bin/env bash
set -euo pipefail

lock_dir=${VARDE_LOCK_DIR:-/Users/alec/source/.varde-measure.lock}
timeout_s=${VARDE_LOCK_TIMEOUT_S-}
# If a holder dies, inspect its PID before manually removing this stale lock.
# The helper never steals a lock based on a PID check.

if (($# == 0)); then
  echo "usage: dev/scripts/with-lock.sh <command> [args...]" >&2
  exit 2
fi

if [[ -n $timeout_s && ! $timeout_s =~ ^[0-9]+$ ]]; then
  echo "VARDE_LOCK_TIMEOUT_S must be a non-negative integer" >&2
  exit 2
fi
start=$SECONDS

while true; do
  if mkdir_error=$(mkdir "$lock_dir" 2>&1); then
    break
  else
    status=$?
    if [[ ! -d $lock_dir || $mkdir_error != *"File exists"* ]]; then
      printf 'could not create lock directory %s (mkdir status %d): %s\n' "$lock_dir" "$status" "$mkdir_error" >&2
      exit "$status"
    fi
    if [[ -n $timeout_s ]] && awk -v elapsed="$((SECONDS - start))" -v timeout="$timeout_s" 'BEGIN { exit !(elapsed >= timeout) }'; then
      printf 'timed out waiting for measurement lock %s after %ss\n' "$lock_dir" "$timeout_s" >&2
      exit 75
    fi
    printf 'waiting for measurement lock %s\n' "$lock_dir" >&2
    sleep 1
  fi
done

release_lock() {
  rm -f "$lock_dir/pid" "$lock_dir/label"
  rmdir "$lock_dir"
}
trap release_lock EXIT

printf '%s\n' "$$" >"$lock_dir/pid"
printf '%s\n' "$*" >"$lock_dir/label"
set +e
"$@"
status=$?
exit "$status"
