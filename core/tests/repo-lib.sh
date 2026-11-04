#!/usr/bin/env bash
set -euo pipefail

tmp="$(mktemp -d "${TMPDIR:-/tmp}/repo-lib.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

repo="$tmp/repo"
mkdir -p "$repo/skills/varde-legacy" "$repo/module/src/pkg/skills/varde-module" \
  "$repo/core/tests/lib"
git -C "$repo" init -q
cp "$(dirname "${BASH_SOURCE[0]}")/lib/repo.sh" "$repo/core/tests/lib/repo.sh"
printf '# Legacy\n' > "$repo/skills/varde-legacy/SKILL.md"
printf '# Module\n' > "$repo/module/src/pkg/skills/varde-module/SKILL.md"
ln -s src/pkg/skills "$repo/module/skills"

source "$repo/core/tests/lib/repo.sh"
found=()
while IFS= read -r item; do found+=("$item"); done < <(skill_dirs)
[[ "${found[*]}" == "$repo/skills/varde-legacy $repo/module/skills/varde-module" ]]
[[ "$(skill_dir varde-module)" == "$repo/module/skills/varde-module" ]]

printf '%s\n' 'repo-lib: legacy and module skill discovery passed.'
