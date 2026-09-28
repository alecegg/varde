#!/usr/bin/env bash
set -euo pipefail

skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/build-finish-paths.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/main" "$fixture/config"
git -C "$fixture/main" init -q
git -C "$fixture/main" config user.email eval@example.invalid
git -C "$fixture/main" config user.name 'Varde Eval'
git -C "$fixture/main" commit -qm initial --allow-empty
git -C "$fixture/main" worktree add -qb linked "$fixture/linked"

VARDE_CONFIG_DIR="$fixture/config" varde-workflow paths set \
  --project "$fixture/main" \
  --working "$fixture/main-working" \
  --knowledge "$fixture/main-knowledge" --json >/dev/null
main_paths="$(cd "$fixture/main" && VARDE_CONFIG_DIR="$fixture/config" varde-workflow paths --json)"
linked_paths="$(cd "$fixture/linked" && VARDE_CONFIG_DIR="$fixture/config" varde-workflow paths --json)"
for field in root working knowledge; do
  main_value="$(jq -r --arg field "$field" '.data[$field]' <<< "$main_paths")"
  linked_value="$(jq -r --arg field "$field" '.data[$field]' <<< "$linked_paths")"
  [[ "$main_value" != null && "$main_value" = "$linked_value" ]] || {
    echo "FAIL: linked worktree did not share repository $field" >&2
    exit 1
  }
done

python3 - "$skills_dir/varde-change/references/build-plan-finish.md" <<'PY'
from pathlib import Path
import re
import sys

text = re.sub(r'\s+', ' ', Path(sys.argv[1]).read_text())
assert text.count("parent's resolved absolute `<working>` and `<knowledge>` paths") == 2
assert 'reviewer to use those paths without re-resolving' in text
assert 'executor uses them without re-resolving' in text
PY
echo 'Build finish briefs preserve parent paths and linked worktrees share repository memory.'
