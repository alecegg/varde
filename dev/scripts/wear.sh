#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

if [[ ${1-} == --locked ]]; then
  shift
else
  if (($# < 2)); then
    echo "usage: dev/scripts/wear.sh <label> <command> [args...]" >&2
    exit 2
  fi
  exec "$script_dir/with-lock.sh" "$script_dir/wear.sh" --locked "$@"
fi

if (($# < 2)); then
  echo "usage: dev/scripts/wear.sh <label> <command> [args...]" >&2
  exit 2
fi

label=$1
shift
trials=${TRIALS:-3}
if [[ ! $trials =~ ^[1-9][0-9]*$ ]]; then
  echo "TRIALS must be a positive integer" >&2
  exit 2
fi

ioreg_bytes() {
  ioreg -c IOBlockStorageDriver -r -w0 |
    awk '/"Bytes \(Write\)"=/ { line=$0; sub(/^.*"Bytes \(Write\)"=/, "", line); sub(/[^0-9].*$/, "", line); total += line; count++ } END { if (count == 0) exit 2; print total+0 }'
}

median() {
  printf '%s\n' "$@" | sort -n | sed -n "$((( $# + 1 ) / 2))p"
}
min() { printf '%s\n' "$@" | sort -n | head -n 1; }
max() { printf '%s\n' "$@" | sort -n | tail -n 1; }

idle_deltas=()
command_deltas=()
durations=()
exits=()
idle_targets=()
sleep_seconds=1

for ((trial = 1; trial <= trials; trial++)); do
  command_before=$(ioreg_bytes) || { echo "ioreg counter unreadable before $label trial $trial" >&2; exit 2; }
  start_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
  rc=0
  "$@" || rc=$?
  end_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
  command_after=$(ioreg_bytes) || { echo "ioreg counter unreadable after $label trial $trial" >&2; exit 2; }

  command_delta=$((command_after - command_before))
  elapsed_ns=$((end_ns - start_ns))
  elapsed_ms=$((elapsed_ns / 1000000))
  sleep_seconds=$(awk -v ms="$elapsed_ns" 'BEGIN { printf "%.6f", ms / 1000000000 }')
  idle_ms=$((elapsed_ns / 1000000))

  idle_before=$(ioreg_bytes) || { echo "ioreg counter unreadable before idle trial $trial" >&2; exit 2; }
  sleep "$sleep_seconds"
  idle_after=$(ioreg_bytes) || { echo "ioreg counter unreadable after idle trial $trial" >&2; exit 2; }
  idle_delta=$((idle_after - idle_before))

  idle_deltas+=("$idle_delta")
  command_deltas+=("$command_delta")
  durations+=("$elapsed_ms")
  exits+=("$rc")
  idle_targets+=("$idle_ms")
done

idle_min=$(min "${idle_deltas[@]}")
idle_max=$(max "${idle_deltas[@]}")
for ((index = 0; index < trials; index++)); do
  within_idle=false
  if ((command_deltas[index] >= idle_min && command_deltas[index] <= idle_max)); then
    within_idle=true
  fi
  printf 'ROW|%s|trial=%d|idle_bytes=%d|idle_target_ms=%d|command_bytes=%d|wall_ms=%d|exit=%d|within_idle_range=%s\n' \
    "$label" "$((index + 1))" "${idle_deltas[index]}" "${idle_targets[index]}" "${command_deltas[index]}" \
    "${durations[index]}" "${exits[index]}" "$within_idle"
done

printf 'SUMMARY|%s|trials=%d|idle_median=%d|idle_range=%d-%d|command_median=%d|command_range=%d-%d|wall_median_ms=%d|exit_codes=%s\n' \
  "$label" "$trials" "$(median "${idle_deltas[@]}")" "$idle_min" "$idle_max" \
  "$(median "${command_deltas[@]}")" "$(min "${command_deltas[@]}")" "$(max "${command_deltas[@]}")" \
  "$(median "${durations[@]}")" "$(IFS=,; printf '%s' "${exits[*]}")"

for rc in "${exits[@]}"; do
  if ((rc != 0)); then exit "$rc"; fi
done
