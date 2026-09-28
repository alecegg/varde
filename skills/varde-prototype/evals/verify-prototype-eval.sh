#!/usr/bin/env bash
set -euo pipefail

emit() { jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a, verdict:$v, evidence:$e}'; }

case "$EVAL_ID" in
  1)
    n=0
    bad=0
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      n=$((n + 1))
      grep -q '<a href' "$f" || bad=1
      grep -q '<script' "$f" && bad=1
    done < <(find memory-bank/working/prototypes/dashboard-layout -maxdepth 1 -type f -name 'variant-*.html' 2>/dev/null)
    v1=FAIL; [[ "$n" -eq 3 ]] && v1=PASS
    v2=FAIL; [[ "$n" -eq 3 && "$bad" -eq 0 ]] && v2=PASS
    v3=PASS; [[ -e memory-bank/working/prototypes/dashboard-layout/v1.html ]] && v3=FAIL
    printf '%s\n' \
      "$(emit "Exactly three variant-*.html files exist at the evaluation storage path" "$v1" "found $n variant-*.html files")" \
      "$(emit "Each discovered variant contains an <a href and no <script tag" "$v2" "checked <a href> and absence of <script> across $n variant file(s)")" \
      "$(emit "v1.html is absent before direction selection" "$v3" "checked initial round output")" \
      | jq -s '{results: .}'
    ;;
  4)
    root=memory-bank/working/prototypes/profile-panel
    n=0
    [[ ! -d "$root" ]] || n=$(find "$root" -maxdepth 1 -type f -name 'variant-*.html' | wc -l | tr -d ' ')
    v1=FAIL; [[ -f "$root/v1.html" ]] && v1=PASS
    v2=FAIL; [[ "$n" -eq 0 ]] && v2=PASS
    printf '%s\n' \
      "$(emit "v1.html exists for an up-front specific direction" "$v1" "checked $root/v1.html")" \
      "$(emit "No variant files are generated for an up-front specific direction" "$v2" "found $n variant-*.html files")" \
      | jq -s '{results: .}'
    ;;
  3)
    found=""
    expected=memory-bank/working/prototypes/order-cancellation/logic.html
    [[ -f "$expected" ]] && found="$expected"
    v=FAIL; [[ -n "$found" ]] && v=PASS
    e="logic.html missing"; [[ -n "$found" ]] && e="logic.html found on disk"
    emit "logic.html exists at the requested evaluation path" "$v" "$e" | jq -s '{results: .}'
    ;;
  *) printf '{"results":[]}' ;;
esac
