#!/usr/bin/env bash
# Snapshot files before simplify edits them, and restore them on failure.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: snapshot.sh save <backup-dir> <path>...
       snapshot.sh restore <backup-dir> [<path>...]

save     Records each path, relative to the repository root, before its
         first edit: an existing file is copied to <backup-dir>/files/<path>;
         a missing one is recorded as new. Later saves of a recorded path
         keep the first snapshot.
restore  Copies saved files back and deletes recorded new files. With no
         paths, restores everything recorded in <backup-dir>.

Exit codes:
  0  done
  1  usage error, unrecorded path, or copy failure
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi
[ $# -ge 2 ] || { usage >&2; exit 1; }
action="$1"
case "$action" in
  save) backup="$(mkdir -p "$2" && cd "$2" && pwd)" ;;
  restore)
    [ -f "$2/manifest" ] || fail "no snapshot manifest at $2/manifest"
    backup="$(cd "$2" && pwd)"
    ;;
  *) usage >&2; exit 1 ;;
esac
shift 2
root="$(git rev-parse --show-toplevel)"
manifest="$backup/manifest"
touch "$manifest"

# Print a path as repo-relative with "." and ".." resolved, so "./x" and "x"
# match. An absolute path's parent directory is resolved physically; the last
# component is kept, so a symlink is recorded as itself.
relative() {
  local target="$1" dir part out=""
  if [ "${target#/}" != "$target" ]; then
    dir="$(cd "$(dirname "$target")" 2>/dev/null && pwd -P)" || fail "no directory for $target"
    target="$dir/$(basename "$target")"
    case "$target" in
      "$root"/*) target="${target#"$root"/}" ;;
      *) fail "$1 is outside $root" ;;
    esac
  fi
  local parts=()
  IFS=/ read -ra parts <<< "$target"
  for part in ${parts[@]+"${parts[@]}"}; do
    case "$part" in
      ""|.) ;;
      ..)
        [ -n "$out" ] || fail "$1 is outside $root"
        case "$out" in */*) out="${out%/*}" ;; *) out="" ;; esac
        ;;
      *) out="${out:+$out/}$part" ;;
    esac
  done
  [ -n "$out" ] || fail "$1 does not name a file"
  printf '%s' "$out"
}

recorded() { cut -f2- "$manifest" | grep -qxF -- "$1"; }

case "$action" in
  save)
    [ $# -ge 1 ] || { usage >&2; exit 1; }
    for arg in "$@"; do
      file="$(relative "$arg")"
      recorded "$file" && continue
      if [ -e "$root/$file" ] || [ -L "$root/$file" ]; then
        mkdir -p "$(dirname "$backup/files/$file")"
        cp -P -p "$root/$file" "$backup/files/$file"
        printf 'saved\t%s\n' "$file" >> "$manifest"
      else
        printf 'new\t%s\n' "$file" >> "$manifest"
      fi
    done
    ;;
  restore)
    if [ $# -eq 0 ]; then
      while IFS= read -r file; do set -- "$@" "$file"; done < <(cut -f2- "$manifest")
    fi
    for arg in "$@"; do
      file="$(relative "$arg")"
      kind="$(awk -F'\t' -v f="$file" '$2 == f { print $1; exit }' "$manifest")"
      case "$kind" in
        saved)
          mkdir -p "$(dirname "$root/$file")"
          rm -f "$root/$file"  # never write through a symlink
          cp -P -p "$backup/files/$file" "$root/$file"
          ;;
        new) rm -f "$root/$file" ;;
        *) fail "$file was not saved in $backup" ;;
      esac
      echo "restored $file"
    done
    ;;
  *) usage >&2; exit 1 ;;
esac
