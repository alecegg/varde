#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --quiet --project "$script_dir/.." --locked python -I \
  "$script_dir/pi_durable_smoke_env.py" "$@"
