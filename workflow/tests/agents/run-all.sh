#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$(basename "${BASH_SOURCE[0]}")"

# Every test runs; none is registered by hand.
failed=()
for test_script in "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/*.py; do
  name="$(basename "$test_script")"
  [ "$name" = "$SELF" ] && continue
  case "$name" in
    *.py) uv run python "$test_script" || failed+=("$name") ;;
    *) bash "$test_script" || failed+=("$name") ;;
  esac
done
if [ "${#failed[@]}" -gt 0 ]; then
  echo "FAIL: ${failed[*]}" >&2
  exit 1
fi

echo "agents checks passed"
