#!/usr/bin/env bash
set -euo pipefail

for browser_tool in playwright chromium google-chrome google-chrome-stable \
  microsoft-edge msedge firefox webkit; do
  if command -v "$browser_tool" >/dev/null 2>&1; then
    printf 'capability=available\n'
    printf 'tool=%s\n' "$browser_tool"
    exit 0
  fi
done

printf 'capability=degraded\n'
printf 'reason=No supported browser tooling found on PATH.\n'
printf 'guidance=Install supported tooling separately, then rerun; no browser evidence was collected.\n'
