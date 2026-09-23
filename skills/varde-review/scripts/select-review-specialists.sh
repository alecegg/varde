#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $(basename "$0") comma-separated-risk-signals" >&2
  exit 2
fi

IFS=',' read -r -a signals <<< "$1"

has_signal() {
  local wanted="$1"
  local raw_signal signal
  for raw_signal in "${signals[@]}"; do
    signal="${raw_signal//[[:space:]]/}"
    [ "$signal" = "$wanted" ] && return 0
  done
  return 1
}

selected=()
for risk_signal in security data-integrity resilience performance api-design; do
  has_signal "$risk_signal" || continue
  selected+=("$risk_signal")
  [ "${#selected[@]}" -lt 2 ] || break
done

if [ "${#selected[@]}" -gt 0 ]; then
  printf '%s\n' "${selected[@]}"
fi
