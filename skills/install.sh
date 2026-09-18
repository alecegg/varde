#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET="$HOME/.claude/skills"
OWNERSHIP_MARKER=.varde-managed-skill

CATALOGUE=(
  varde-explore
  varde-change
  varde-review
  varde-docs
  varde-knowledge
  varde-prototype
  varde-agent-doc-authoring
)

RETIRED=(
  varde-build
  varde-define
  varde-code-codebase-navigation
  varde-code-rule-authoring
  varde-code-rule-scan-triage
  varde-dashboard
  varde-explain
  varde-friction
  varde-friction-distillation
  varde-handoff
  varde-onboard
  varde-orchestrate
  varde-plan
  varde-reflect
  varde-review-fix
  varde-simplify
  varde-spec
  varde-worktree
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [-d target_dir] [-s skill1,skill2,...] [-f] [-n] [--yes]

  -d target_dir   Install into this directory
  -s skills       Install an explicit comma-separated subset
  -f              Overwrite selected consolidated directories
  -n              Show planned writes without changing files
  --yes           Approve unmarked legacy-directory removal
  -h              Show this help

Default target: $DEFAULT_TARGET
EOF
}

TARGET="$DEFAULT_TARGET"
SKILLS=""
FORCE=0
DRY_RUN=0
ASSUME_YES=0
PRESERVE_LEGACY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -d)
      [ "$#" -ge 2 ] || { echo "-d requires a value" >&2; exit 1; }
      TARGET="$2"
      shift 2
      ;;
    -s)
      [ "$#" -ge 2 ] || { echo "-s requires a value" >&2; exit 1; }
      SKILLS="$2"
      shift 2
      ;;
    -f) FORCE=1; shift ;;
    -n) DRY_RUN=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --preserve-legacy) PRESERVE_LEGACY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [ -n "$SKILLS" ]; then
  IFS=',' read -ra SELECTED <<< "$SKILLS"
else
  SELECTED=("${CATALOGUE[@]}")
fi

for skill in "${SELECTED[@]}"; do
  known=0
  for candidate in "${CATALOGUE[@]}"; do
    [ "$skill" = "$candidate" ] && known=1
  done
  if [ "$known" -ne 1 ]; then
    echo "Unknown skill: $skill" >&2
    exit 1
  fi
done

marked_retired=("")
unmarked_retired=("")
for skill in "${RETIRED[@]}"; do
  destination="$TARGET/$skill"
  [ -d "$destination" ] || continue
  if [ -f "$destination/$OWNERSHIP_MARKER" ] &&
    grep -Fxq 'varde-managed-skill' "$destination/$OWNERSHIP_MARKER"; then
    marked_retired+=("$destination")
  else
    unmarked_retired+=("$destination")
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  for destination in "${marked_retired[@]}"; do
    [ -n "$destination" ] || continue
    echo "Would remove managed legacy directory: $destination"
  done
  for destination in "${unmarked_retired[@]}"; do
    [ -n "$destination" ] || continue
    if [ "$ASSUME_YES" -eq 1 ]; then
      echo "Would remove approved legacy directory: $destination"
    else
      echo "Would request removal approval: $destination"
    fi
  done
else
  for destination in "${marked_retired[@]}"; do
    [ -n "$destination" ] || continue
    rm -rf "$destination"
    echo "Removed managed legacy directory: $destination"
  done

  remove_unmarked=0
  unmarked_count=$((${#unmarked_retired[@]} - 1))
  if [ "$unmarked_count" -gt 0 ]; then
    if [ "$ASSUME_YES" -eq 1 ]; then
      remove_unmarked=1
    elif [ "$PRESERVE_LEGACY" -eq 1 ]; then
      remove_unmarked=0
    else
      printf 'Remove %d unmarked legacy skill directories? [y/N] ' "$unmarked_count"
      reply=""
      read -r reply || true
      case "$reply" in
        [yY]|[yY][eE][sS]) remove_unmarked=1 ;;
      esac
    fi
  fi

  if [ "$remove_unmarked" -eq 1 ]; then
    for destination in "${unmarked_retired[@]}"; do
      [ -n "$destination" ] || continue
      rm -rf "$destination"
      echo "Removed legacy directory: $destination"
    done
  else
    for destination in "${unmarked_retired[@]}"; do
      [ -n "$destination" ] || continue
      echo "Preserved unmarked legacy directory: $destination"
    done
  fi

  mkdir -p "$TARGET"
fi

for skill in "${SELECTED[@]}"; do
  source_dir="$SCRIPT_DIR/$skill"
  destination="$TARGET/$skill"

  if [ "$DRY_RUN" -eq 1 ]; then
    find "$source_dir" -type f \
      -not -path '*/evals/*' \
      -not -path '*-workspace/*' \
      -not -name '.DS_Store' | while IFS= read -r source_file; do
      printf 'Would install %s -> %s/%s\n' "$source_file" "$destination" "${source_file#"$source_dir"/}"
    done
    printf 'Would install marker -> %s/%s\n' "$destination" "$OWNERSHIP_MARKER"
    continue
  fi

  if [ -e "$destination" ] && [ "$FORCE" -ne 1 ]; then
    read -r -p "Overwrite existing $destination? [y/N] " reply
    case "$reply" in
      [yY]*) ;;
      *) echo "Skipped $skill"; continue ;;
    esac
  fi

  rm -rf "$destination"
  cp -R "$source_dir" "$destination"
  find "$destination" -type d \( -name evals -o -name '*-workspace' \) \
    -prune -exec rm -rf {} +
  find "$destination" -name '.DS_Store' -delete
  printf 'varde-managed-skill\n' > "$destination/$OWNERSHIP_MARKER"
  echo "Installed $skill -> $destination"
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run. No skills installed to: $TARGET"
else
  echo "Done. Installed to: $TARGET"
fi
