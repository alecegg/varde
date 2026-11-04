#!/usr/bin/env bash
set -euo pipefail

exec python3 "${EVAL_SKILL_DIR}/evals/verify-navigation.py" "$@"
