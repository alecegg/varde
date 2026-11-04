#!/usr/bin/env bash
# Print the files and changed line ranges in scope for simplify mode.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: change-ranges.sh [--staged | --ref <ref>] [-- <path>...]

Prints one line per in-scope file: <repo-relative path><TAB><ranges>.
<ranges> is "all" for an untracked file, otherwise comma-separated
start-end line ranges added or changed in the new version. Files with only
deletions are omitted.

Sources:
  (default)    working tree and staged changes vs HEAD, plus untracked files
  --staged     staged changes vs HEAD only
  --ref <ref>  working tree vs <ref>, plus untracked files
Paths after -- narrow any source to those files.

Exit codes:
  0  printed the scope (empty output means nothing to simplify)
  1  usage error or git failure
EOF
}

base=HEAD
staged=false
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --staged) staged=true; shift ;;
    --ref) [ $# -ge 2 ] || { usage >&2; exit 1; }; base="$2"; shift 2 ;;
    --) shift; break ;;
    *) usage >&2; exit 1 ;;
  esac
done

diff_args=(-c core.quotePath=false diff --no-ext-diff --no-color -U0 --src-prefix=a/ --dst-prefix=b/)
if $staged; then
  diff_args+=(--cached HEAD)
else
  diff_args+=("$base")
fi

git "${diff_args[@]}" -- "$@" | awk '
  function flush() { if (path != "" && ranges != "") print path "\t" ranges }
  # File headers appear only between "diff --git" and the first hunk, so an
  # added line that starts with "++ " is never mistaken for a header.
  /^diff --git / { flush(); path = ""; ranges = ""; header = 1; next }
  header && /^\+\+\+ / {
    path = ($0 == "+++ /dev/null") ? "" : substr($0, 7)
    sub(/\t$/, "", path)  # git appends a tab when the name has spaces
    next
  }
  /^@@ / {
    header = 0
    split($3, added, ",")
    start = substr(added[1], 2) + 0
    count = (2 in added) ? added[2] + 0 : 1
    if (count > 0) ranges = ranges (ranges == "" ? "" : ",") start "-" (start + count - 1)
  }
  END { flush() }
'

if ! $staged; then
  git -c core.quotePath=false ls-files --others --exclude-standard --full-name -- "${@:-:/}" |
    while IFS= read -r file; do printf '%s\tall\n' "$file"; done
fi
