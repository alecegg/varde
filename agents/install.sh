#!/usr/bin/env bash
# Installs varde agents into a Claude / Codex / opencode agents directory.
#
# Each agent lives in its own folder here (build/, explore/, plan/, review/)
# with one variant file per harness:
#   claude.md    -> installed as <name>.md   in a Claude agents dir
#   codex.toml   -> installed as <name>.toml in a Codex agents dir
#   opencode.md  -> installed as <name>.md   in an opencode agent dir
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HARNESS="claude"
TARGET=""
AGENTS=""
FORCE=0
MANAGED=0
DRY_RUN=0
OWNERSHIP_MARKER="varde-managed-agent"

usage() {
  cat <<EOF
Usage: $(basename "$0") [-t harness] [-d target_dir] [-a agent1,agent2,...] [-f] [-m] [-n]

  -t harness      Harness to install for: claude | codex | opencode (default: claude)
  -d target_dir   Directory to install into (default depends on harness):
                    claude   -> \$HOME/.claude/agents
                    codex    -> \$HOME/.codex/agents
                    opencode -> \$HOME/.config/opencode/agent
  -a agents       Comma-separated agent names to install (default: all)
  -f              Overwrite existing agent files without prompting
  -m              Overwrite only varde-managed files; preserve other files
  -n              Show planned writes without changing files
  -h              Show this help

Examples:
  $(basename "$0")                          # all agents, Claude
  $(basename "$0") -t codex                 # all agents, Codex
  $(basename "$0") -t opencode -a plan,review
  $(basename "$0") -t claude -d ./.claude/agents   # into a repo-local dir
EOF
}

while getopts "t:d:a:fmnh" opt; do
  case "$opt" in
    t) HARNESS="$OPTARG" ;;
    d) TARGET="$OPTARG" ;;
    a) AGENTS="$OPTARG" ;;
    f) FORCE=1 ;;
    m) MANAGED=1 ;;
    n) DRY_RUN=1 ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [ "$FORCE" -eq 1 ] && [ "$MANAGED" -eq 1 ]; then
  echo "-f and -m cannot be combined" >&2
  exit 1
fi

case "$HARNESS" in
  claude)   VARIANT="claude.md";   EXT="md";   DEFAULT_TARGET="$HOME/.claude/agents" ;;
  codex)    VARIANT="codex.toml";  EXT="toml"; DEFAULT_TARGET="$HOME/.codex/agents" ;;
  opencode) VARIANT="opencode.md"; EXT="md";   DEFAULT_TARGET="$HOME/.config/opencode/agent" ;;
  *) echo "Unknown harness: $HARNESS (expected claude|codex|opencode)" >&2; exit 1 ;;
esac

[ -n "$TARGET" ] || TARGET="$DEFAULT_TARGET"

ALL_AGENTS=()
while IFS= read -r line; do
  ALL_AGENTS+=("$line")
done < <(find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort)

if [ -n "$AGENTS" ]; then
  SELECTED=()
  IFS=',' read -ra SELECTED <<< "$AGENTS"
else
  SELECTED=("${ALL_AGENTS[@]}")
fi

for agent in "${SELECTED[@]}"; do
  if [[ ! " ${ALL_AGENTS[*]} " =~ " ${agent} " ]]; then
    echo "Unknown agent: $agent" >&2
    exit 1
  fi
done

if [ "$DRY_RUN" -ne 1 ]; then
  mkdir -p "$TARGET"
fi

is_varde_managed() {
  grep -Fq "$OWNERSHIP_MARKER" "$1"
}

mark_varde_managed() {
  case "$EXT" in
    md) printf '\n<!-- %s -->\n' "$OWNERSHIP_MARKER" >>"$1" ;;
    toml) printf '\n# %s\n' "$OWNERSHIP_MARKER" >>"$1" ;;
  esac
}

for agent in "${SELECTED[@]}"; do
  src="$SCRIPT_DIR/$agent/$VARIANT"
  dest="$TARGET/$agent.$EXT"
  if [ ! -f "$src" ]; then
    echo "No $HARNESS variant for $agent (missing $src)" >&2
    exit 1
  fi
  if [ -e "$dest" ] && [ "$MANAGED" -eq 1 ] && ! is_varde_managed "$dest"; then
    echo "Preserved unowned $dest"
    continue
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'Would install %s -> %s\n' "$src" "$dest"
    continue
  fi
  if [ -e "$dest" ] && [ "$FORCE" -ne 1 ] && [ "$MANAGED" -ne 1 ]; then
    read -r -p "Overwrite existing $dest? [y/N] " reply
    case "$reply" in
      [yY]*) ;;
      *) echo "Skipped $agent"; continue ;;
    esac
  fi
  cp "$src" "$dest"
  if [ "$MANAGED" -eq 1 ]; then
    mark_varde_managed "$dest"
  fi
  echo "Installed $agent -> $dest"
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run. No $HARNESS agents installed to: $TARGET"
else
  echo "Done. Installed $HARNESS agents to: $TARGET"
fi
