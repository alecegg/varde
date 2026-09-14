#!/usr/bin/env bash
# Installs varde-* skills into a Claude/opencode skills directory of your choice.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET="$HOME/.claude/skills"

usage() {
  cat <<EOF
Usage: $(basename "$0") [-d target_dir] [-s skill1,skill2,...] [-f]

  -d target_dir   Directory to install skills into (default: $DEFAULT_TARGET)
  -s skills       Comma-separated list of skill names to install (default: all)
  -f              Overwrite existing skill directories without prompting
  -h              Show this help

Examples:
  $(basename "$0")
  $(basename "$0") -d ~/.config/opencode/skills
  $(basename "$0") -s varde-plan,varde-review
EOF
}

TARGET="$DEFAULT_TARGET"
SKILLS=""
FORCE=0

while getopts "d:s:fh" opt; do
  case "$opt" in
    d) TARGET="$OPTARG" ;;
    s) SKILLS="$OPTARG" ;;
    f) FORCE=1 ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

ALL_SKILLS=()
while IFS= read -r line; do
  ALL_SKILLS+=("$line")
done < <(find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 -type d -name 'varde-*' -exec basename {} \; | sort)

if [ -n "$SKILLS" ]; then
  SELECTED=()
  IFS=',' read -ra SELECTED <<< "$SKILLS"
else
  SELECTED=("${ALL_SKILLS[@]}")
fi

for skill in "${SELECTED[@]}"; do
  if [[ ! " ${ALL_SKILLS[*]} " =~ " ${skill} " ]]; then
    echo "Unknown skill: $skill" >&2
    exit 1
  fi
done

mkdir -p "$TARGET"

for skill in "${SELECTED[@]}"; do
  src="$SCRIPT_DIR/$skill"
  dest="$TARGET/$skill"
  if [ -e "$dest" ] && [ "$FORCE" -ne 1 ]; then
    read -r -p "Overwrite existing $dest? [y/N] " reply
    case "$reply" in
      [yY]*) ;;
      *) echo "Skipped $skill"; continue ;;
    esac
  fi
  rm -rf "$dest"
  cp -R "$src" "$dest"
  # Strip author-only artifacts so end users never see them: eval test cases
  # (evals/) and any generated eval-run workspace are for skill development and
  # quality iteration, not needed at runtime.
  rm -rf "$dest/evals" "$dest"/*-workspace
  find "$dest" -name '.DS_Store' -delete
  echo "Installed $skill -> $dest"
done

echo "Done. Installed to: $TARGET"
