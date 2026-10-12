#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ASSET_DIR="$REPO_ROOT/docs/service"
PLIST="$ASSET_DIR/watch-service.plist"
UNIT="$ASSET_DIR/watch-service.service"
TIMER="$ASSET_DIR/watch-service.timer"

fail() {
  echo "service-templates: FAIL: $*" >&2
  exit 1
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

if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$PLIST" >/dev/null || fail "plutil rejected the launchd plist"
else
  echo "service-templates: SKIP: plutil is unavailable"
fi

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify "$UNIT" "$TIMER" || fail "systemd-analyze rejected the user units"
else
  echo "service-templates: SKIP: systemd-analyze is unavailable"
fi

echo "service-templates: pass"
