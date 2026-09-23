#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $(basename "$0") candidate-file" >&2
  exit 2
fi

candidate_file="$1"
[ -r "$candidate_file" ] || {
  echo "Candidate file is not readable: $candidate_file" >&2
  exit 2
}

is_supported_category() {
  case "$1" in
    code|architecture|security|readability|correctness|resilience|observability|performance|api-design|data-integrity)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_supported_severity() {
  case "$1" in
    critical|high|medium|low|info) return 0 ;;
    *) return 1 ;;
  esac
}

seen_keys=""
while IFS= read -r record || [ -n "$record" ]; do
  case "$record" in
    ''|\#*) continue ;;
  esac

  field_count="$(printf '%s\n' "$record" | awk -F '\t' '{ print NF }')"
  if [ "$field_count" -ne 7 ]; then
    echo "malformed candidate rejected: expected seven tab-separated fields" >&2
    continue
  fi

  location="$(printf '%s\n' "$record" | cut -f1)"
  category="$(printf '%s\n' "$record" | cut -f2)"
  severity="$(printf '%s\n' "$record" | cut -f3)"
  evidence="$(printf '%s\n' "$record" | cut -f4)"
  impact="$(printf '%s\n' "$record" | cut -f5)"
  refutation="$(printf '%s\n' "$record" | cut -f6)"
  suggested_disposition="$(printf '%s\n' "$record" | cut -f7)"

  if [ -z "$location" ] || [ -z "$category" ] || [ -z "$severity" ] ||
    [ -z "$evidence" ] || [ -z "$impact" ] || [ -z "$refutation" ] ||
    [ -z "$suggested_disposition" ]; then
    echo "incomplete candidate rejected: required field is empty" >&2
    continue
  fi
  if ! is_supported_category "$category"; then
    echo "unsupported category rejected: $category" >&2
    continue
  fi
  if ! is_supported_severity "$severity"; then
    echo "unsupported severity rejected: $severity" >&2
    continue
  fi

  key="$category|$location|$impact"
  if printf '%s' "$seen_keys" | grep -Fqx "$key"; then
    echo "duplicate candidate rejected: $key" >&2
    continue
  fi

  seen_keys+="$key"$'\n'
  printf '%s\n' "$record"
done < "$candidate_file"
