#!/usr/bin/env bash
# Installs varde agents into a Claude / Codex / opencode / Pi agents directory.
#
# Each agent lives in its own folder here (varde-executor/, varde-explorer/, varde-planner/, varde-reviewer/)
# with one variant file per harness:
#   claude.md    -> installed as <name>.md   in a Claude agents dir
#   codex.toml   -> installed as <name>.toml in a Codex agents dir
#   opencode.md  -> installed as <name>.md   in an opencode agent dir (OpenCode 1.x)
#   opencode-v2.md -> installed as <name>.md in an opencode agent dir (OpenCode 2+)
#   pi.md        -> installed as <name>.md   in a Pi agents dir ($PI_CODING_AGENT_DIR/agents)
# The OpenCode major comes from VARDE_AGENTS_OPENCODE_VERSION, else `opencode --version`;
# unknown means 1.x.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HARNESS="claude"
TARGET=""
CUSTOM_TARGET=0
AGENTS=""
FORCE=0
MANAGED=0
DRY_RUN=0
OWNERSHIP_MARKER="varde-managed-agent"
PRESERVE_HELPER="$SCRIPT_DIR/preserve-models.py"

usage() {
  cat <<EOF
Usage: $(basename "$0") [-t harness] [-d target_dir] [-a agent1,agent2,...] [-f] [-m] [-n]

  -t harness      Harness to install for: claude | codex | opencode | pi (default: claude)
                  (opencode installs the 2.x adapter when OpenCode 2+ is detected, else 1.x)
  -d target_dir   Directory to install into (default depends on harness):
                    claude   -> \$HOME/.claude/agents
                    codex    -> \$HOME/.codex/agents
                    opencode -> \$HOME/.config/opencode/agents
                    pi       -> \$PI_CODING_AGENT_DIR/agents, else \$HOME/.pi/agent/agents
  -a agents       Comma-separated agent names to install (default: all)
  -f              Overwrite existing agent files without prompting
  -m              Overwrite only varde-managed files; preserve other files
  -n              Show planned writes without changing files
  -h              Show this help

Examples:
  $(basename "$0")                          # all agents, Claude
  $(basename "$0") -t codex                 # all agents, Codex
  $(basename "$0") -t pi                    # all agents, Pi
  $(basename "$0") -t opencode -a varde-planner,varde-reviewer
  $(basename "$0") -t claude -d ./.claude/agents   # into a repo-local dir
EOF
}

while getopts "t:d:a:fmnh" opt; do
  case "$opt" in
    t) HARNESS="$OPTARG" ;;
    d) TARGET="$OPTARG"; CUSTOM_TARGET=1 ;;
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

# Echo the major version of OpenCode, or nothing when it cannot be determined.
opencode_major() {
  local version="${VARDE_AGENTS_OPENCODE_VERSION:-}"
  if [ -z "$version" ] && command -v opencode >/dev/null 2>&1; then
    version="$(opencode --version 2>/dev/null || true)"
  fi
  { printf '%s\n' "$version" | grep -Eo '[0-9]+(\.[0-9]+)?' | head -n 1 | cut -d. -f1; } || true
}

opencode_variant() {
  local major
  major="$(opencode_major)"
  if [ -n "$major" ] && [ "$major" -ge 2 ]; then echo "opencode-v2.md"; else echo "opencode.md"; fi
}

case "$HARNESS" in
  claude)   VARIANT="claude.md";   EXT="md";   DEFAULT_TARGET="$HOME/.claude/agents" ;;
  codex)    VARIANT="codex.toml";  EXT="toml"; DEFAULT_TARGET="$HOME/.codex/agents" ;;
  opencode) VARIANT="$(opencode_variant)"; EXT="md";   DEFAULT_TARGET="$HOME/.config/opencode/agents" ;;
  pi)       VARIANT="pi.md";       EXT="md";   DEFAULT_TARGET="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/agents" ;;
  *) echo "Unknown harness: $HARNESS (expected claude|codex|opencode|pi)" >&2; exit 1 ;;
esac

[ -n "$TARGET" ] || TARGET="$DEFAULT_TARGET"

ALL_AGENTS=()
while IFS= read -r line; do
  ALL_AGENTS+=("$line")
done < <(
  for agent_dir in "$SCRIPT_DIR"/*/; do
    if [ -f "$agent_dir/claude.md" ] ||
      [ -f "$agent_dir/codex.toml" ] ||
      [ -f "$agent_dir/opencode.md" ] ||
      [ -f "$agent_dir/pi.md" ]; then
      basename "$agent_dir"
    fi
  done | sort
)

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
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  grep -Fqx -e "<!-- $OWNERSHIP_MARKER -->" -e "# $OWNERSHIP_MARKER" "$1"
}

mark_varde_managed() {
  case "$EXT" in
    md) printf '\n<!-- %s -->\n' "$OWNERSHIP_MARKER" >>"$1" ;;
    toml) printf '\n# %s\n' "$OWNERSHIP_MARKER" >>"$1" ;;
  esac
}

remove_stale_build() {
  local stale="$TARGET/build.$EXT"
  if is_varde_managed "$stale"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'Would remove stale managed %s\n' "$stale"
    else
      rm "$stale"
      printf 'Removed stale managed %s\n' "$stale"
    fi
  fi
}

# Agents renamed to varde-* names; -m/-f installs retire the old managed files.
old_name_for() {
  case "$1" in
    varde-explorer) echo explore ;;
    varde-planner)  echo plan ;;
    varde-reviewer) echo review ;;
    varde-executor) echo executor ;;
  esac
}

remove_renamed() {
  local old stale
  old="$(old_name_for "$1")"
  [ -n "$old" ] || return 0
  { [ "$MANAGED" -eq 1 ] || [ "$FORCE" -eq 1 ]; } || return 0
  stale="$TARGET/$old.$EXT"
  if is_varde_managed "$stale"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'Would remove renamed managed %s\n' "$stale"
    else
      rm "$stale"
      printf 'Removed renamed managed %s\n' "$stale"
    fi
  fi
}

# Retire only owned regular files from the legacy singular agent directory, after a
# corresponding adapter is installed in agents/. Explicit targets never affect HOME.
remove_legacy_opencode() {
  local agent="$1" legacy="$HOME/.config/opencode/agent"
  [ "$HARNESS" = "opencode" ] && [ "$CUSTOM_TARGET" -eq 0 ] || return 0
  [ ! -L "$legacy" ] || return 0
  { [ "$MANAGED" -eq 1 ] || [ "$FORCE" -eq 1 ]; } || return 0
  local old candidates=("$legacy/$agent.md") candidate
  old="$(old_name_for "$agent")"
  [ -z "$old" ] || candidates+=("$legacy/$old.md")
  [ "$agent" != "varde-executor" ] || candidates+=("$legacy/build.md")
  for candidate in "${candidates[@]}"; do
    if is_varde_managed "$candidate"; then
      if [ "$DRY_RUN" -eq 1 ]; then
        printf 'Would remove legacy managed %s\n' "$candidate"
      else
        rm "$candidate"
        printf 'Removed legacy managed %s\n' "$candidate"
      fi
    fi
  done
}

# Echo the managed file whose model settings carry over to $2 (agent $1), if
# any: the destination itself, else (under -m/-f) the first managed file that
# the rename, stale-build, or legacy-opencode cleanup would retire.
installed_source() {
  local agent="$1" dest="$2" old candidate candidates=()
  if is_varde_managed "$dest"; then echo "$dest"; return 0; fi
  if exists "$dest" || { [ "$MANAGED" -ne 1 ] && [ "$FORCE" -ne 1 ]; }; then return 0; fi
  old="$(old_name_for "$agent")"
  # Newest layout first: old name, then build, then the opencode V1 dir.
  [ -z "$old" ] || candidates+=("$TARGET/$old.$EXT")
  [ "$agent" != "varde-executor" ] || candidates+=("$TARGET/build.$EXT")
  if [ "$HARNESS" = "opencode" ] && [ "$CUSTOM_TARGET" -eq 0 ] &&
    [ ! -L "$HOME/.config/opencode/agent" ]; then
    candidates+=("$HOME/.config/opencode/agent/$agent.md")
    [ -z "$old" ] || candidates+=("$HOME/.config/opencode/agent/$old.md")
    [ "$agent" != "varde-executor" ] || candidates+=("$HOME/.config/opencode/agent/build.md")
  fi
  for candidate in "${candidates[@]+"${candidates[@]}"}"; do
    if is_varde_managed "$candidate"; then echo "$candidate"; return 0; fi
  done
}

# Run the model-preservation helper on FILE; prints the preserved keys.
# Args: agent file installed_source [--dry-run]
preserve_models() {
  local agent="$1" file="$2" installed="$3" args
  args=(--harness "$HARNESS" --agent "$agent" --staged "$file")
  [ -z "$installed" ] || args+=(--installed "$installed")
  [ -z "${4:-}" ] || args+=(--dry-run)
  python3 -B "$PRESERVE_HELPER" "${args[@]}"
}

exists() {
  [ -e "$1" ] || [ -L "$1" ]
}

# Both preview and installation use this decision. In particular, a link is
# never followed to inspect a marker or to write an installed adapter.
install_action() {
  local destination="$1"
  if ! exists "$destination"; then
    ACTION=install
  elif [ "$MANAGED" -eq 1 ]; then
    if is_varde_managed "$destination"; then ACTION=replace; else ACTION=preserve; fi
  elif [ "$FORCE" -eq 1 ]; then
    ACTION=replace
  elif [ -t 0 ]; then
    ACTION=prompt
  else
    ACTION=refuse
  fi
}

COMPLETED=()
install_failure() {
  printf 'Failed to install %s -> %s\n' "$1" "$2" >&2
  if [ "${#COMPLETED[@]}" -gt 0 ]; then
    printf 'Previously installed: %s\n' "${COMPLETED[*]}" >&2
  fi
  exit 1
}

install_agent() {
  local agent="$1" src="$2" dest="$3" installed="$4" staged backup="" key kept
  staged="$(mktemp "$TARGET/.varde-agent.XXXXXX")" || return 1
  if ! cp -p "$src" "$staged" || ! mark_varde_managed "$staged" ||
    ! kept="$(preserve_models "$agent" "$staged" "$installed")"; then
    rm -f "$staged"
    return 1
  fi
  if exists "$dest"; then
    backup="$(mktemp "$TARGET/.varde-agent-backup.XXXXXX")" || { rm -f "$staged"; return 1; }
    rm -f "$backup" || { rm -f "$staged"; return 1; }
    if ! mv "$dest" "$backup"; then
      rm -f "$staged"
      return 1
    fi
  fi
  if ! mv "$staged" "$dest"; then
    rm -f "$staged"
    if [ -n "$backup" ]; then
      mv "$backup" "$dest" || echo "Rollback failed for $dest; backup at $backup" >&2
    fi
    return 1
  fi
  [ -z "$backup" ] || rm -rf "$backup"
  for key in $kept; do
    printf 'Preserved user model setting %s in %s\n' "$key" "$dest"
  done
}

for agent in "${SELECTED[@]}"; do
  src="$SCRIPT_DIR/$agent/$VARIANT"
  dest="$TARGET/$agent.$EXT"
  if [ ! -f "$src" ]; then
    echo "No $HARNESS variant for $agent (missing $src)" >&2
    install_failure "$agent" "$dest"
  fi
  install_action "$dest"
  if [ "$DRY_RUN" -eq 1 ]; then
    case "$ACTION" in
      install|replace)
        printf 'Would %s %s -> %s\n' "$ACTION" "$src" "$dest"
        kept="$(preserve_models "$agent" "$src" "$(installed_source "$agent" "$dest")" --dry-run)" ||
          install_failure "$agent" "$dest"
        for key in $kept; do
          printf 'Would preserve user model setting %s in %s\n' "$key" "$dest"
        done
        ;;
      preserve) printf 'Would preserve unowned %s\n' "$dest"; continue ;;
      prompt) printf 'Would request confirmation to replace %s\n' "$dest"; continue ;;
      refuse) printf 'Would refuse noninteractive replacement of %s; use -f or -m\n' "$dest" >&2; install_failure "$agent" "$dest" ;;
    esac
    if [ "$agent" = "varde-executor" ] &&
      { [ "$MANAGED" -eq 1 ] || [ "$FORCE" -eq 1 ]; }; then
      remove_stale_build
    fi
    remove_renamed "$agent"
    remove_legacy_opencode "$agent"
    continue
  fi
  case "$ACTION" in
    preserve) echo "Preserved unowned $dest"; continue ;;
    refuse) echo "Refusing to prompt without a TTY for $dest; use -f or -m" >&2; install_failure "$agent" "$dest" ;;
    prompt)
    read -r -p "Overwrite existing $dest? [y/N] " reply
    case "$reply" in
      [yY]*) ;;
      *) echo "Skipped $agent"; continue ;;
    esac
    ;;
  esac
  install_agent "$agent" "$src" "$dest" "$(installed_source "$agent" "$dest")" || install_failure "$agent" "$dest"
  COMPLETED+=("$agent")
  echo "Installed $agent -> $dest"
  remove_legacy_opencode "$agent"
  if [ "$agent" = "varde-executor" ] &&
    { [ "$MANAGED" -eq 1 ] || [ "$FORCE" -eq 1 ]; }; then
    remove_stale_build
  fi
  remove_renamed "$agent"
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run. No $HARNESS agents installed to: $TARGET"
else
  echo "Done. Installed $HARNESS agents to: $TARGET"
fi
