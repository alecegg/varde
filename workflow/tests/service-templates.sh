#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSET_DIR="$SCRIPT_DIR/../docs/service"
PLIST="$ASSET_DIR/watch-service.plist"
UNIT="$ASSET_DIR/watch-service.service"
TIMER="$ASSET_DIR/watch-service.timer"

fail() {
  echo "service-templates: FAIL: $*" >&2
  exit 1
}

skip() {
  if [ -n "${SERVICE_TEMPLATES_REQUIRE_VALIDATORS:-}" ]; then
    fail "$* (SERVICE_TEMPLATES_REQUIRE_VALIDATORS is set)"
  fi
  echo "service-templates: SKIP: $*" >&2
}

for template in "$PLIST" "$UNIT" "$TIMER"; do
  [ -f "$template" ] || fail "missing template: ${template##*/}"
  case "$template" in
    "$TIMER") grep -q -- 'Unit=watch-service.service' "$template" || fail "timer does not start the service" ;;
    *)
      grep -q -- '--once' "$template" || fail "${template##*/} does not use --once"
      grep -q -- '--repo' "$template" || fail "${template##*/} lacks --repo"
      grep -q -- '/path/to/repository' "$template" || fail "${template##*/} lacks the repository placeholder"
      ;;
  esac
  if grep -Eiq '(^|[^[:alnum:]_])(claude|codex|paseo|opencode|pi)([[:space:]_-]|$)|--model|(^|[^[:alnum:]_])model([^[:alnum:]_]|$)' "$template"; then
    fail "${template##*/} contains a model or harness command"
  fi
done

python3 - "$PLIST" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as stream:
    plistlib.load(stream)
PY

if command -v systemd-analyze >/dev/null 2>&1; then
  # systemd requires ExecStart to be executable; point the placeholder at a real one.
  VERIFY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/service-templates.XXXXXX")"
  trap 'rm -rf "$VERIFY_DIR"' EXIT
  sed "s|/path/to/varde|$(command -v true)|" "$UNIT" >"$VERIFY_DIR/${UNIT##*/}"
  cp "$TIMER" "$VERIFY_DIR/"
  systemd-analyze verify "$VERIFY_DIR/${UNIT##*/}" "$VERIFY_DIR/${TIMER##*/}" || fail "systemd-analyze rejected the user units"
else
  skip "systemd-analyze is unavailable; ${UNIT##*/} and ${TIMER##*/} are unverified"
fi

echo "service-templates: pass"
