#!/usr/bin/env bash
set -euo pipefail

# Runs the shipped length checker over every skill's SKILL.md and references.
# Only errors fail; see varde-skill-authoring/references/criteria.md.
source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
if [ "$#" -gt 0 ]; then
  exec varde learn check "$@"
fi
skills=()
while IFS= read -r skill; do skills+=("$skill"); done < <(skill_dirs)
if [ "${#skills[@]}" -eq 0 ]; then
  echo "no source skills found" >&2
  exit 1
fi
exec varde learn check "${skills[@]}"
