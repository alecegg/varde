#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Every test runs; none is registered by hand. A hand-kept list is how most of
# this suite went unrun while two of its tests rotted.
failed=()
for test_script in "$SCRIPT_DIR"/*.sh; do
  [ "$(basename "$test_script")" = "$(basename "${BASH_SOURCE[0]}")" ] && continue
  if [ ! -x "$test_script" ]; then
    echo "FAIL: $(basename "$test_script") is not executable" >&2
    failed+=("$(basename "$test_script")")
    continue
  fi
  "$test_script" || failed+=("$(basename "$test_script")")
done
"$SCRIPT_DIR/../check-refs.sh" || failed+=("check-refs.sh")
if [ "${#failed[@]}" -gt 0 ]; then
  echo "FAIL: ${failed[*]}" >&2
  exit 1
fi

echo "benchmark foundation checks passed"
