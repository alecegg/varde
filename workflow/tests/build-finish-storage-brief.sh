#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$REPO_ROOT/workflow/tests/lib/varde-bin.sh"
prefer_checkout_varde "$REPO_ROOT"

fixture="$(mktemp -d "${TMPDIR:-/tmp}/build-finish-paths.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/main" "$fixture/config"
git -C "$fixture/main" init -q
git -C "$fixture/main" config user.email eval@example.invalid
git -C "$fixture/main" config user.name 'Varde Eval'
git -C "$fixture/main" commit -qm initial --allow-empty
git -C "$fixture/main" worktree add -qb linked "$fixture/linked"

VARDE_CONFIG_DIR="$fixture/config" varde setup paths set \
  --project "$fixture/main" \
  --working "$fixture/main-working" \
  --knowledge "$fixture/main-knowledge" --json >/dev/null
main_paths="$(cd "$fixture/main" && VARDE_CONFIG_DIR="$fixture/config" varde setup paths --json)"
linked_paths="$(cd "$fixture/linked" && VARDE_CONFIG_DIR="$fixture/config" varde setup paths --json)"
for field in root working knowledge; do
  main_value="$(jq -r --arg field "$field" '.data[$field]' <<< "$main_paths")"
  linked_value="$(jq -r --arg field "$field" '.data[$field]' <<< "$linked_paths")"
  [[ "$main_value" != null && "$main_value" = "$linked_value" ]] || {
    echo "FAIL: linked worktree did not share repository $field" >&2
    exit 1
  }
done

echo 'Linked worktrees resolve the same repository memory paths.'
