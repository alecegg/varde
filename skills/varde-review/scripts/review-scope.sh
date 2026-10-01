#!/usr/bin/env bash
# Resolve the files, comparison base, and read size for a report-mode review.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: review-scope.sh area [<path>...]
       review-scope.sh diff [--ref <ref>] [-- <path>...]

area  Tracked plus untracked, nonignored files under the paths (whole
      repository when none are given), whether or not they changed.
diff  Changed files. Target: <ref>...HEAD with --ref; otherwise working tree
      vs HEAD plus untracked files; on a clean tree, changes since the nearest
      v* tag, else since the merge base with origin/HEAD. Paths narrow the list.

Output: "# key<TAB>value" header lines (target; base, the commit to read
deleted paths from with `git show <base>:<path>`; files; bytes; tokens,
approximately bytes/4 of listed files plus the diff), then one
"<status><TAB><repo-relative path>" line per file. Status is a git diff
letter (A, M, D, ...), "?" for untracked, or "T" for a tracked file in area
mode.

Exit codes:
  0  printed the scope (files 0 means nothing to review)
  1  usage error, git failure, or no comparison target on a clean tree
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

[ $# -ge 1 ] || { usage >&2; exit 1; }
case "$1" in -h|--help) usage; exit 0 ;; esac
mode="$1"
shift
root="$(git rev-parse --show-toplevel)"
git_q() { git -c core.quotePath=false "$@"; }
# ":/" makes an empty path list cover the whole repository, not just the cwd.
untracked() { git_q ls-files --others --exclude-standard --full-name -- "${@:-:/}" | awk '{ print "?\t" $0 }'; }

target=""
base=""
diff_bytes=0
case "$mode" in
  area)
    target="area ${*:-.}"
    list="$(git_q ls-files --full-name -- "${@:-:/}" | awk '{ print "T\t" $0 }'; untracked "$@")"
    ;;
  diff)
    ref=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --ref) [ $# -ge 2 ] || { usage >&2; exit 1; }; ref="$2"; shift 2 ;;
        --) shift; break ;;
        *) usage >&2; exit 1 ;;
      esac
    done
    if [ -z "$ref" ] && { ! git diff --quiet HEAD || [ -n "$(untracked)" ]; }; then
      target="working tree vs HEAD"
      base="$(git rev-parse HEAD)"
      list="$(git_q diff --no-renames --name-status HEAD -- "$@"; untracked "$@")"
      diff_bytes="$(git diff --no-ext-diff HEAD -- "$@" | wc -c)"
    else
      if [ -z "$ref" ]; then
        ref="$(git describe --tags --match 'v*' --abbrev=0 2>/dev/null)" ||
          ref="$(git merge-base HEAD origin/HEAD 2>/dev/null)" ||
          fail "clean tree with no v* tag or origin/HEAD; name a ref"
      fi
      target="$ref...HEAD"
      base="$(git merge-base "$ref" HEAD)"
      list="$(git_q diff --no-renames --name-status "$base" HEAD -- "$@")"
      diff_bytes="$(git diff --no-ext-diff "$base" HEAD -- "$@" | wc -c)"
    fi
    ;;
  *) usage >&2; exit 1 ;;
esac

files=0
bytes=$((diff_bytes))
while IFS=$'\t' read -r status path; do
  [ -n "$path" ] || continue
  files=$((files + 1))
  if [ -f "$root/$path" ]; then bytes=$((bytes + $(wc -c < "$root/$path"))); fi
done <<< "$list"

printf '# target\t%s\n' "$target"
[ -z "$base" ] || printf '# base\t%s\n' "$base"
printf '# files\t%s\n# bytes\t%s\n# tokens\t%s\n' "$files" "$bytes" "$((bytes / 4))"
[ -z "$list" ] || printf '%s\n' "$list"
