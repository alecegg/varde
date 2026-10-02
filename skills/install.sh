#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET="$HOME/.agents/skills"
OWNERSHIP_MARKER=.varde-managed-skill

# The catalogue is every varde-*/ directory holding a SKILL.md. This excludes
# eval-tools/ (no SKILL.md, and not a varde-* name): maintainer-only eval
# tooling never ships to an installed harness.
CATALOGUE=()
for skill_manifest in "$SCRIPT_DIR"/varde-*/SKILL.md; do
  [ -e "$skill_manifest" ] || continue
  skill_name="$(basename "$(dirname "$skill_manifest")")"
  CATALOGUE+=("$skill_name")
done

RETIRED=(
  varde-browser
  varde-diagnose
  varde-release
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [-d target_dir] [-s skill1,skill2,...] [-l source_dir] [-f] [-m] [-n]

  -d target_dir   Install into this directory
  -s skills       Install an explicit comma-separated subset
  -l source_dir   Link skills from this canonical directory into the target
  -f              Overwrite existing installs without prompting
  -m              Overwrite only varde-managed installs; preserve unowned dirs
  -n              Preview install decisions without changing files
  -h              Show this help

Default target: $DEFAULT_TARGET
EOF
}

TARGET="$DEFAULT_TARGET"
SKILLS=""
SKILLS_SPECIFIED=0
LINK_SOURCE=""
FORCE=0
MANAGED=0
DRY_RUN=0

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
        SKILLS_SPECIFIED=1
        shift 2
        ;;
      -l)
        [ "$#" -ge 2 ] || { echo "-l requires a value" >&2; exit 1; }
        LINK_SOURCE="$2"
        shift 2
        ;;
      -f) FORCE=1; shift ;;
      -m) MANAGED=1; shift ;;
      -n) DRY_RUN=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
  done
  validate_install_options
}

validate_install_options() {
  if [ "$FORCE" -eq 1 ] && [ "$MANAGED" -eq 1 ]; then
    echo "-f and -m cannot be combined" >&2
    exit 1
  fi
  if [ -n "$LINK_SOURCE" ]; then
    case "$LINK_SOURCE" in
      /*) ;;
      *) echo "-l requires an absolute source directory" >&2; exit 1 ;;
    esac
    [ "$TARGET" != "$LINK_SOURCE" ] || {
      echo "Cannot link a skill directory into itself" >&2
      exit 1
    }
  fi
}

select_default_skills() {
  if [ "$SKILLS_SPECIFIED" -eq 1 ]; then
    case "$SKILLS" in
      ""|,*|*,|*,,*) echo "-s requires nonempty comma-separated skill names" >&2; exit 1 ;;
    esac
    IFS=',' read -ra RAW_SELECTED <<< "$SKILLS"
    SELECTED=()
    local skill already existing
    for skill in "${RAW_SELECTED[@]}"; do
      already=0
      for existing in "${SELECTED[@]-}"; do
        [ "$existing" = "$skill" ] && already=1 && break
      done
      [ "$already" -eq 1 ] || SELECTED+=("$skill")
    done
  else
    SELECTED=("${CATALOGUE[@]}")
  fi
}

known_skill() {
  local skill_name="$1"
  local candidate
  for candidate in "${CATALOGUE[@]}"; do
    [ "$skill_name" = "$candidate" ] && return 0
  done
  return 1
}

included_skill_paths() {
  local source_root="$1"
  find "$source_root" \
    \( -type d \( -name evals -o -name '*-workspace' \) -prune \) -o \
    \( -name '.*' ! -path "$source_root" -prune \) -o \
    -print0
}

copy_skill_tree() {
  local source_root="$1" destination_root="$2"
  local source_path relative_path target_path
  [ -d "$source_root" ] || return 1
  mkdir -p "$destination_root" || return 1
  included_skill_paths "$source_root" | while IFS= read -r -d '' source_path; do
    [ "$source_path" != "$source_root" ] || continue
    relative_path="${source_path#"$source_root"/}"
    target_path="$destination_root/$relative_path"
    if [ -d "$source_path" ] && [ ! -L "$source_path" ]; then
      mkdir -p "$target_path" || exit 1
    elif [ -L "$source_path" ]; then
      echo "Symlink in skill package: $source_path" >&2
      exit 1
    elif [ -f "$source_path" ]; then
      cp -p "$source_path" "$target_path" || exit 1
    else
      echo "Unsupported skill entry: $source_path" >&2
      exit 1
    fi
  done
}

SHARED_ROOT="$SCRIPT_DIR/shared"
SHARED_MANIFEST="$SHARED_ROOT/MANIFEST"

# Relative paths this skill lists in skills/shared/MANIFEST (`<path> <skill>...`).
shared_files_for_skill() {
  local skill="$1" line rel_path skills_field
  [ -f "$SHARED_MANIFEST" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    rel_path="${line%% *}"
    skills_field=" ${line#* } "
    case "$skills_field" in
      *" $skill "*) printf '%s\n' "$rel_path" ;;
    esac
  done < "$SHARED_MANIFEST"
}

copy_shared_files() {
  local skill="$1" staged="$2" rel_path source_file target_file
  while IFS= read -r rel_path; do
    [ -n "$rel_path" ] || continue
    source_file="$SHARED_ROOT/$rel_path"
    target_file="$staged/$rel_path"
    [ -f "$source_file" ] || return 1
    mkdir -p "$(dirname "$target_file")" || return 1
    cp -p "$source_file" "$target_file" || return 1
  done < <(shared_files_for_skill "$skill")
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

# Remove retired skills this installer placed. A directory without the
# ownership marker was not installed by varde and is never touched.
retired_installs=("")

find_retired_installs() {
  local skill destination
  for skill in "${RETIRED[@]}"; do
    destination="$TARGET/$skill"
    # A link to the canonical copy is ours even after that copy is gone.
    if [ -n "$LINK_SOURCE" ] && [ -L "$destination" ] &&
       [ "$(readlink "$destination")" = "$LINK_SOURCE/$skill" ]; then
      retired_installs+=("$destination")
      continue
    fi
    [ -f "$destination/$OWNERSHIP_MARKER" ] || continue
    grep -Fxq 'varde-managed-skill' "$destination/$OWNERSHIP_MARKER" || continue
    retired_installs+=("$destination")
  done
}

remove_retired_installs() {
  local destination
  for destination in "${retired_installs[@]}"; do
    [ -n "$destination" ] || continue
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "Would remove retired skill: $destination"
    else
      rm -rf "$destination"
      echo "Removed retired skill: $destination"
    fi
  done
  [ "$DRY_RUN" -eq 1 ] || mkdir -p "$TARGET"
}

preview_skill_install() {
  local source_dir="$1" destination="$2" source_file rel_path
  if [ -n "$LINK_SOURCE" ]; then
    printf 'Would link %s -> %s\n' "$LINK_SOURCE/$(basename "$source_dir")" "$destination"
    return
  fi
  included_skill_paths "$source_dir" | while IFS= read -r -d '' source_file; do
    [ -f "$source_file" ] || continue
    printf 'Would install %s -> %s/%s\n' "$source_file" "$destination" "${source_file#"$source_dir"/}"
  done
  while IFS= read -r rel_path; do
    [ -n "$rel_path" ] || continue
    printf 'Would install %s -> %s/%s\n' "$SHARED_ROOT/$rel_path" "$destination" "$rel_path"
  done < <(shared_files_for_skill "$(basename "$source_dir")")
  printf 'Would install marker -> %s/%s\n' "$destination" "$OWNERSHIP_MARKER"
}

is_varde_managed_skill() {
  local destination="$1"
  [ ! -L "$destination" ] && [ -f "$destination/$OWNERSHIP_MARKER" ] &&
    grep -Fxq 'varde-managed-skill' "$destination/$OWNERSHIP_MARKER"
}

destination_exists() {
  [ -e "$1" ] || [ -L "$1" ]
}

COMPLETED=()
install_failure() {
  printf 'Failed to install %s -> %s\n' "$1" "$2" >&2
  if [ "${#COMPLETED[@]}" -gt 0 ]; then
    printf 'Previously installed: %s\n' "${COMPLETED[*]}" >&2
  fi
  exit 1
}

confirm_replace() {
  local destination="$1" reply
  if [ ! -t 0 ]; then
    echo "Refusing to prompt without a TTY for $destination; use -f or -m" >&2
    return 2
  fi
  read -r -p "Overwrite existing $destination? [y/N] " reply
  case "$reply" in
    [yY]*) return 0 ;;
    *) return 1 ;;
  esac
}

install_skill() {
  local skill="$1" source_dir destination staged backup=""
  ITEM_INSTALLED=0
  source_dir="$SCRIPT_DIR/$skill"
  destination="$TARGET/$skill"
  staged="$(mktemp -d "$TARGET/.varde-skill.XXXXXX")" || return 1
  if [ -n "$LINK_SOURCE" ]; then
    rmdir "$staged" || return 1
    ln -s "$LINK_SOURCE/$skill" "$staged" || return 1
  else
    if ! copy_skill_tree "$source_dir" "$staged" || [ ! -f "$staged/SKILL.md" ] ||
       ! copy_shared_files "$skill" "$staged" ||
       ! printf 'varde-managed-skill\n' > "$staged/$OWNERSHIP_MARKER"; then
      rm -rf "$staged"
      return 1
    fi
  fi
  if destination_exists "$destination"; then
    backup="$(mktemp -d "$TARGET/.varde-skill-backup.XXXXXX")" || { rm -rf "$staged"; return 1; }
    rmdir "$backup" || { rm -rf "$staged"; return 1; }
    if ! mv "$destination" "$backup"; then
      rm -rf "$staged"
      return 1
    fi
  fi
  if ! mv "$staged" "$destination"; then
    rm -rf "$staged"
    if [ -n "$backup" ]; then
      mv "$backup" "$destination" || echo "Rollback failed for $destination; backup at $backup" >&2
    fi
    return 1
  fi
  [ -z "$backup" ] || rm -rf "$backup"
  ITEM_INSTALLED=1
  if [ -n "$LINK_SOURCE" ]; then echo "Linked $skill -> $destination";
  else echo "Installed $skill -> $destination"; fi
}

preflight_skill_install() {
  local skill="$1" destination="$TARGET/$1" confirm_status source_root symlink canonical_unwritten
  PREFLIGHT_ACTION=install
  # Under a dry run, a canonical pass into $LINK_SOURCE never wrote it (see
  # the DRY_RUN guard on `mkdir -p "$TARGET"` above), so a missing
  # $LINK_SOURCE directory itself is that same dry run's own doing, not a
  # real problem: both the canonical-skill check and the symlink scan below
  # fall back to the real on-disk skill source in that case. If $LINK_SOURCE
  # does exist (an earlier real install, or a source unrelated to this dry
  # run — including one deliberately missing or containing a symlink) the
  # normal checks against it still apply.
  canonical_unwritten=0
  [ "$DRY_RUN" -eq 1 ] && [ -n "$LINK_SOURCE" ] && [ ! -d "$LINK_SOURCE" ] && canonical_unwritten=1

  if [ -n "$LINK_SOURCE" ] && [ ! -f "$LINK_SOURCE/$skill/SKILL.md" ] && [ "$canonical_unwritten" -ne 1 ]; then
    echo "Missing canonical skill: $LINK_SOURCE/$skill" >&2
    return 1
  fi
  if [ "$canonical_unwritten" -eq 1 ]; then
    source_root="$SCRIPT_DIR/$skill"
  else
    source_root="${LINK_SOURCE:-$SCRIPT_DIR}/$skill"
  fi
  symlink="$(find "$source_root" -type l -print -quit)" || return 1
  if [ -n "$symlink" ]; then
    echo "Symlink in skill package: $symlink" >&2
    return 1
  fi
  if [ -n "$LINK_SOURCE" ] && [ -L "$destination" ] &&
     [ "$(readlink "$destination")" = "$LINK_SOURCE/$skill" ]; then
    echo "Already linked $skill -> $destination"
    PREFLIGHT_ACTION=skip
    return
  fi
  if destination_exists "$destination" && [ "$MANAGED" -eq 1 ] && ! is_varde_managed_skill "$destination"; then
    echo "Preserved unowned $destination"
    PREFLIGHT_ACTION=skip
    return
  fi
  if destination_exists "$destination" && [ "$FORCE" -ne 1 ] && [ "$MANAGED" -ne 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      if [ ! -t 0 ]; then
        echo "Would ask to overwrite existing $destination; real install without a TTY would refuse (use -f or -m)"
        PREFLIGHT_ACTION=skip
        return
      fi
      echo "Would ask to overwrite existing $destination; installation depends on confirmation"
      PREFLIGHT_ACTION=skip
      return
    fi
    if confirm_replace "$destination"; then
      :
    else
      confirm_status=$?
      if [ "$confirm_status" -eq 1 ]; then
        echo "Skipped $skill"
        PREFLIGHT_ACTION=skip
        return
      fi
      return "$confirm_status"
    fi
  fi
}

check_readable_ownership_markers() {
  local skill destination marker
  [ "$MANAGED" -eq 1 ] || return 0
  for skill in "${SELECTED[@]-}"; do
    [ -n "$skill" ] || continue
    destination="$TARGET/$skill"
    marker="$destination/$OWNERSHIP_MARKER"
    if destination_exists "$destination" && [ ! -L "$destination" ] &&
       [ -f "$marker" ] && [ ! -r "$marker" ]; then
      printf 'Cannot read ownership marker: %s\n' "$marker" >&2
      return 1
    fi
  done
}

install_selected_skills() {
  local skill source_dir destination
  check_readable_ownership_markers || return 1
  for skill in "${SELECTED[@]-}"; do
    [ -n "$skill" ] || continue
    source_dir="$SCRIPT_DIR/$skill"
    destination="$TARGET/$skill"
    preflight_skill_install "$skill" || install_failure "$skill" "$destination"
    [ "$PREFLIGHT_ACTION" = install ] || continue
    if [ "$DRY_RUN" -eq 1 ]; then
      preview_skill_install "$source_dir" "$destination"
    else
      install_skill "$skill" || install_failure "$skill" "$destination"
      [ "$ITEM_INSTALLED" -eq 0 ] || COMPLETED+=("$skill")
    fi
  done
}

parse_arguments "$@"
select_default_skills
validate_selected_skills
find_retired_installs
remove_retired_installs
install_selected_skills || exit 1

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run. No skills installed to: $TARGET"
else
  echo "Done. Installed to: $TARGET"
  # Skills require the varde CLIs; sync reports missing ones itself.
  if [ -z "$LINK_SOURCE" ] && [ -z "${VARDE_SKILLS_SKIP_CLI_CHECK:-}" ]; then
    missing_clis=""
    for cli in varde-workflow varde-code varde-toz varde-learn; do
      command -v "$cli" >/dev/null 2>&1 || missing_clis="$missing_clis $cli"
    done
    [ -z "$missing_clis" ] ||
      echo "Warning: varde CLIs missing from PATH:$missing_clis. Install them with: $(cd "$SCRIPT_DIR/.." && pwd)/varde sync" >&2
  fi
fi
