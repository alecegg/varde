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

# Optional packs stay separate from the core catalogue. Future packs extend
# their own membership list without making another pack a runtime dependency.
BROWSER_PACK=(varde-browser)
SHIPPING_PACK=(varde-release)
DIAGNOSTICS_PACK=(varde-diagnose)

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
Usage: $(basename "$0") [-d target_dir] [-s skill1,skill2,...] [--pack pack] [-f] [-n] [--yes]

  -d target_dir   Install into this directory
  -s skills       Install an explicit comma-separated subset, including optional skills
  --pack pack     Install one optional pack: browser, diagnostics, or shipping
  -f              Overwrite selected consolidated directories
  -n              Show planned writes without changing files
  --yes           Approve unmarked legacy-directory removal
  -h              Show this help

Default target: $DEFAULT_TARGET
EOF
}

TARGET="$DEFAULT_TARGET"
SKILLS=""
PACK_REQUESTS=()
PACK_REQUEST_COUNT=0
FORCE=0
DRY_RUN=0
ASSUME_YES=0
PRESERVE_LEGACY=0

parse_arguments() {
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
      --pack)
        [ "$#" -ge 2 ] || { echo "--pack requires a value" >&2; exit 1; }
        PACK_REQUESTS+=("$2")
        PACK_REQUEST_COUNT=$((PACK_REQUEST_COUNT + 1))
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
}

select_default_skills() {
  if [ -n "$SKILLS" ]; then
    IFS=',' read -ra SELECTED <<< "$SKILLS"
  elif [ "$PACK_REQUEST_COUNT" -gt 0 ]; then
    SELECTED=()
  else
    SELECTED=("${CATALOGUE[@]}")
  fi
}

known_skill() {
  local skill_name="$1"
  local candidate
  for candidate in "${CATALOGUE[@]}" "${BROWSER_PACK[@]}" "${SHIPPING_PACK[@]-}" "${DIAGNOSTICS_PACK[@]}"; do
    [ "$skill_name" = "$candidate" ] && return 0
  done
  return 1
}

append_unique() {
  local skill_name="$1"
  local selected_skill
  for selected_skill in "${SELECTED[@]-}"; do
    [ -n "$selected_skill" ] || continue
    [ "$selected_skill" = "$skill_name" ] && return 0
  done
  SELECTED+=("$skill_name")
}

portable_mode() {
  local source_path="$1" mode
  if mode=$(stat -f '%Lp' "$source_path" 2>/dev/null); then
    printf '%s\n' "$mode"
  else
    stat -c '%a' "$source_path"
  fi
}

included_skill_paths() {
  local source_root="$1"
  find "$source_root" \
    \( -type d \( -name evals -o -name '*-workspace' \) -prune \) -o \
    \( -name '.DS_Store' -prune \) -o \
    -print0
}

copy_skill_tree() {
  local source_root="$1" destination_root="$2"
  local source_path relative_path target_path
  [ -d "$source_root" ] || return 1
  mkdir -p "$destination_root"
  included_skill_paths "$source_root" | while IFS= read -r -d '' source_path; do
    [ "$source_path" != "$source_root" ] || continue
    relative_path="${source_path#"$source_root"/}"
    target_path="$destination_root/$relative_path"
    if [ -d "$source_path" ] && [ ! -L "$source_path" ]; then
      mkdir -p "$target_path"
    elif [ -L "$source_path" ]; then
      cp -Pp "$source_path" "$target_path"
    elif [ -f "$source_path" ]; then
      cp -p "$source_path" "$target_path"
    else
      echo "Unsupported skill entry: $source_path" >&2
      exit 1
    fi
  done
}

preserve_skill_directory_modes() {
  local source_root="$1" destination_root="$2"
  local source_path relative_path target_path
  included_skill_paths "$source_root" | while IFS= read -r -d '' source_path; do
    [ -d "$source_path" ] && [ ! -L "$source_path" ] || continue
    if [ "$source_path" = "$source_root" ]; then
      target_path="$destination_root"
    else
      relative_path="${source_path#"$source_root"/}"
      target_path="$destination_root/$relative_path"
    fi
    chmod "$(portable_mode "$source_path")" "$target_path"
  done
}

add_requested_packs() {
  local pack_name skill_name
  local pack_skills
  for pack_name in "${PACK_REQUESTS[@]-}"; do
    [ -n "$pack_name" ] || continue
    case "$pack_name" in
      browser) pack_skills=("${BROWSER_PACK[@]}") ;;
      shipping) pack_skills=("${SHIPPING_PACK[@]-}") ;;
      diagnostics) pack_skills=("${DIAGNOSTICS_PACK[@]}") ;;
      *)
        echo "Unknown pack: $pack_name" >&2
        exit 1
        ;;
    esac
    for skill_name in "${pack_skills[@]-}"; do
      [ -n "$skill_name" ] || continue
      append_unique "$skill_name"
    done
  done
}

validate_selected_skills() {
  local skill
  for skill in "${SELECTED[@]-}"; do
    [ -n "$skill" ] || continue
    if ! known_skill "$skill"; then
      echo "Unknown skill: $skill" >&2
      exit 1
    fi
  done
}

marked_retired=("")
unmarked_retired=("")

classify_retired_skills() {
  local skill destination
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
}

preview_retired_cleanup() {
  local destination
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
}

confirm_unmarked_removal() {
  local unmarked_count reply
  unmarked_count=$((${#unmarked_retired[@]} - 1))
  [ "$unmarked_count" -gt 0 ] || return 1
  [ "$ASSUME_YES" -ne 1 ] || return 0
  [ "$PRESERVE_LEGACY" -ne 1 ] || return 1

  printf 'Remove %d unmarked legacy skill directories? [y/N] ' "$unmarked_count"
  reply=""
  read -r reply || true
  case "$reply" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

remove_retired_skills() {
  local destination remove_unmarked=0
  for destination in "${marked_retired[@]}"; do
    [ -n "$destination" ] || continue
    rm -rf "$destination"
    echo "Removed managed legacy directory: $destination"
  done

  confirm_unmarked_removal && remove_unmarked=1

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
}

preview_skill_install() {
  local source_dir="$1" destination="$2" source_file
  find "$source_dir" -type f \
    -not -path '*/evals/*' \
    -not -path '*-workspace/*' \
    -not -name '.DS_Store' | while IFS= read -r source_file; do
    printf 'Would install %s -> %s/%s\n' "$source_file" "$destination" "${source_file#"$source_dir"/}"
  done
  printf 'Would install marker -> %s/%s\n' "$destination" "$OWNERSHIP_MARKER"
}

install_skill() {
  local skill="$1" source_dir destination reply
  source_dir="$SCRIPT_DIR/$skill"
  destination="$TARGET/$skill"
  if [ -e "$destination" ] && [ "$FORCE" -ne 1 ]; then
    read -r -p "Overwrite existing $destination? [y/N] " reply
    case "$reply" in
      [yY]*) ;;
      *) echo "Skipped $skill"; return ;;
    esac
  fi

  rm -rf "$destination"
  copy_skill_tree "$source_dir" "$destination"
  printf 'varde-managed-skill\n' > "$destination/$OWNERSHIP_MARKER"
  preserve_skill_directory_modes "$source_dir" "$destination"
  echo "Installed $skill -> $destination"
}

install_selected_skills() {
  local skill source_dir destination
  for skill in "${SELECTED[@]-}"; do
    [ -n "$skill" ] || continue
    source_dir="$SCRIPT_DIR/$skill"
    destination="$TARGET/$skill"
    if [ "$DRY_RUN" -eq 1 ]; then
      preview_skill_install "$source_dir" "$destination"
    else
      install_skill "$skill"
    fi
  done
}

parse_arguments "$@"
select_default_skills
add_requested_packs
validate_selected_skills
classify_retired_skills
if [ "$DRY_RUN" -eq 1 ]; then
  preview_retired_cleanup
else
  remove_retired_skills
fi
install_selected_skills

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run. No skills installed to: $TARGET"
else
  echo "Done. Installed to: $TARGET"
fi
