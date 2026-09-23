#!/usr/bin/env bash
set -euo pipefail

for release_tool in kubectl helm terraform aws gcloud az flyctl railway vercel; do
  if command -v "$release_tool" >/dev/null 2>&1; then
    printf 'capability=available\n'
    printf 'tool=%s\n' "$release_tool"
    exit 0
  fi
done

printf 'capability=degraded\n'
printf 'reason=No supported release provider tooling found on PATH.\n'
printf 'guidance=Install provider tooling separately, then rerun; no release mutation was attempted.\n'
