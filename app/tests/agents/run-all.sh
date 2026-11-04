#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
uv run python "$SCRIPT_DIR/generated-config-contracts.py"
uv run python "$SCRIPT_DIR/opencode-v2-permissions.py"
bash "$SCRIPT_DIR/generated-adapters.sh"
echo "app agent generation checks passed"
