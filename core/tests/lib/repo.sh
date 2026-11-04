#!/usr/bin/env bash
# Shared path discovery for shell tests that run before and after module moves.

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")/../.." rev-parse --show-toplevel)"

skill_dir() {
  local name="$1"
  local candidate
  for candidate in "$REPO_ROOT/skills/$name" "$REPO_ROOT"/*/skills/"$name"; do
    if [ -d "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf 'skill not found: %s\n' "$name" >&2
  return 1
}

skill_dirs() {
  local repo_root="${1:-$REPO_ROOT}" root candidate
  for root in "$repo_root/skills" "$repo_root"/*/skills; do
    [ -d "$root" ] || continue
    for candidate in "$root"/varde-*; do
      [ -d "$candidate" ] || continue
      printf '%s\n' "$candidate"
    done
  done
}

shared_skills_dir() {
  local candidate
  for candidate in "$REPO_ROOT"/core/src/varde_core/skills/shared \
    "$REPO_ROOT"/*/src/varde_core/skills/shared; do
    if [ -f "$candidate/MANIFEST" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf 'shared skills directory not found under %s\n' "$REPO_ROOT" >&2
  return 1
}
