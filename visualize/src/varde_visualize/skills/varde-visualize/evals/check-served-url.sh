#!/usr/bin/env bash
# Usage: check-served-url.sh <url>
# Asserts the served visualization is on loopback and returns HTTP 200.
set -euo pipefail

url="${1:?usage: check-served-url.sh <url>}"
case "$url" in
  http://127.0.0.1:*) ;;
  *) echo "FAIL: not a 127.0.0.1 URL: $url" >&2; exit 1 ;;
esac
code="$(curl -s -o /dev/null -w '%{http_code}' "$url")"
[ "$code" = "200" ] || { echo "FAIL: HTTP $code from $url" >&2; exit 1; }
echo "PASS: HTTP 200 from $url"
