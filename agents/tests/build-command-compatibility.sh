#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -Fq '"build": "varde-change build"' "$AGENTS_DIR/capabilities.json"
grep -Fq 'varde-change build' "$AGENTS_DIR/varde-builder/claude.md"
grep -Fq 'varde-change build' "$AGENTS_DIR/varde-builder/codex.toml"
grep -Fq 'varde-change build' "$AGENTS_DIR/varde-builder/opencode.md"
if rg -n 'varde-change exe.cutor|varde-change build-agent' \
  "$AGENTS_DIR/capabilities.json" \
  "$AGENTS_DIR"/{varde-builder,varde-planner,varde-reviewer,varde-explorer}; then
  echo "FAIL: lifecycle command compatibility was changed" >&2
  exit 1
fi

echo "Build command compatibility passed."
