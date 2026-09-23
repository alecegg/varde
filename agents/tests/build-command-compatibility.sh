#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -Fq '"build": "varde-change build"' "$AGENTS_DIR/capabilities.json"
grep -Fq 'varde-change build' "$AGENTS_DIR/executor/claude.md"
grep -Fq 'varde-change build' "$AGENTS_DIR/executor/codex.toml"
grep -Fq 'varde-change build' "$AGENTS_DIR/executor/opencode.md"
if rg -n 'varde-change executor|varde-change build-agent' \
  "$AGENTS_DIR/capabilities.json" "$AGENTS_DIR/install.sh" \
  "$AGENTS_DIR"/{executor,plan,review,explore}; then
  echo "FAIL: lifecycle command compatibility was changed" >&2
  exit 1
fi

echo "Build command compatibility passed."
