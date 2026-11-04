#!/usr/bin/env bash
# Print "skill route main_min_tokens main_max_tokens" for each route of each
# skill; with no arguments, the skills of this repository are used.
#
# usage: route-metrics.sh [skill-dir...]
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
source "$repo_root/core/tests/lib/repo.sh"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/route-metrics.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/home" "$tmp_dir/config" "$tmp_dir/data"
export HOME="$tmp_dir/home"
export XDG_CONFIG_HOME="$tmp_dir/config"
export VARDE_CONFIG_DIR="$tmp_dir/config/varde"
export XDG_DATA_HOME="$tmp_dir/data"

candidates=("$@")
if [ "$#" -eq 0 ]; then
  while IFS= read -r skill_dir; do
    candidates+=("$skill_dir")
  done < <(skill_dirs "$repo_root")
fi

skill_dirs=()
for skill_dir in ${candidates[@]+"${candidates[@]}"}; do
  [[ -f "$skill_dir/SKILL.md" ]] && skill_dirs+=("$skill_dir")
done

flow_file="$tmp_dir/flow.json"
varde learn measure "${skill_dirs[@]}" flow --json > "$flow_file"

python3 - "$flow_file" <<'PY'
import json
import sys
from pathlib import Path

flow = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for skill in flow["data"]:
    for route in skill["routes"]:
        print(
            f'{skill["skill"]}\t{route["route"]}\t'
            f'{route["main_min_tokens"]}\t{route["main_max_tokens"]}'
        )
PY
