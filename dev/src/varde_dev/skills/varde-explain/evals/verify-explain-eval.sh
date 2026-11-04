#!/usr/bin/env bash
set -euo pipefail
emit() { jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a, verdict:$v, evidence:$e}'; }
root=working/explanations
pages() { [[ -d "$root" ]] && find "$root" -maxdepth 1 -type f -name '*.md' | sort || true; }
page_checks() {
  # $1 = shape label, remaining = required headings
  local label="$1"; shift
  local count file dated=FAIL heads=PASS export=FAIL
  count=$(pages | wc -l | tr -d ' '); file=$(pages | head -1)
  [[ $count -eq 1 && "${file##*/}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$ ]] && dated=PASS
  for h in "$@"; do
    [[ $count -eq 1 ]] && grep -Eiq "^#+ +$h\$" "$file" || heads=FAIL
  done
  local html="${file%.md}.html"
  [[ $count -eq 1 && -f "$html" ]] && ! grep -Eiq '<script' "$html" && export=PASS
  printf '%s\n' \
    "$(emit "One dated $label page (.md) exists under the working explanations directory" "$dated" "found $count page(s)")" \
    "$(emit "The page has the required headings" "$heads" 'checked required headings')" \
    "$(emit 'The page is exported with `varde learn docs build` and the export holds no script' "$export" 'checked the .html export and absence of <script')" \
    | jq -s '{results: .}'
}
case "$EVAL_ID" in
  1) page_checks explanation Background Intuition 'How It Works' ;;
  7) page_checks options Options Tradeoffs Recommendation ;;
  2|3|5)
    n=$(pages | wc -l | tr -d ' ')
    v=PASS; [[ "$n" -eq 0 ]] || v=FAIL
    emit 'No explanation page is written for a chat response or unresolved ambiguity' "$v" "found $n page(s)" | jq -s '{results: .}' ;;
  *) printf '{"results":[]}' ;;
esac
