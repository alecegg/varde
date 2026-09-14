#!/usr/bin/env bash
# Regenerates duplicated reference files from the canonical copies in _shared/,
# so installed skills stay self-contained (install.sh copies one skill dir at
# a time) while the repo's source of truth for shared text lives in one place.
#
# Run this after editing anything in _shared/, before committing.
#   ./sync-shared-refs.sh            # regenerate the synced reference files
#   ./sync-shared-refs.sh --check    # verify they match _shared/; non-zero on drift
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED="$SCRIPT_DIR/_shared"

MODE=sync
if [ "${1:-}" = "--check" ]; then
  MODE=check
elif [ -n "${1:-}" ]; then
  echo "Usage: $(basename "$0") [--check]" >&2
  exit 1
fi
DRIFT=0

# emit <target-relpath> : content is read from stdin. In sync mode it writes the
# target; in check mode it reports (but never fixes) any difference.
emit() {
  local rel="$1" target="$SCRIPT_DIR/$1" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [ "$MODE" = check ]; then
    if ! diff -q "$target" "$tmp" >/dev/null 2>&1; then
      echo "DRIFT: $rel is out of sync with _shared/ — run ./sync-shared-refs.sh"
      DRIFT=1
    fi
    rm -f "$tmp"
  else
    mkdir -p "$(dirname "$target")"
    mv "$tmp" "$target"
    echo "synced $rel"
  fi
}

sync_plain() {
  local name="$1"; shift
  for skill in "$@"; do
    emit "$skill/references/$name" < "$SHARED/$name"
  done
}

sync_with_append() {
  local name="$1" skill="$2" append="$3"
  emit "$skill/references/$name" < <(cat "$SHARED/$name" "$SHARED/$append")
}

sync_plain INTERVIEW.md varde-build varde-review-fix
sync_with_append INTERVIEW.md varde-plan INTERVIEW.append.varde-plan.md

sync_plain DESIGN-VOCABULARY.md varde-plan

for pair in "varde-build:build" "varde-docs:docs" "varde-explain:explain" "varde-plan:plan" "varde-review:review" "varde-simplify:simplify" "varde-spec:spec"; do
  skill="${pair%%:*}"
  suffix="${pair##*:}"
  emit "$skill/references/VARDE-CODE-CLI.md" < <(cat "$SHARED/VARDE-CODE-CLI-CORE.md" "$SHARED/VARDE-CODE-CLI.$suffix.append.md")
done

for pair in "varde-knowledge:knowledge" "varde-plan:plan" "varde-spec:spec" "varde-docs:docs"; do
  skill="${pair%%:*}"
  suffix="${pair##*:}"
  emit "$skill/references/VARDE-DOCS-CLI.md" < <(cat "$SHARED/VARDE-DOCS-CLI-CORE.md" "$SHARED/VARDE-DOCS-CLI.$suffix.append.md")
done

if [ "$MODE" = check ]; then
  if [ "$DRIFT" -ne 0 ]; then
    echo "Shared reference drift detected." >&2
    exit 1
  fi
  echo "All synced reference files match _shared/."
fi
