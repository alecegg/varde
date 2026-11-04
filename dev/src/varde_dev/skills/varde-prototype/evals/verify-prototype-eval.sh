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
      html="${f%.md}.html"
      [ -f "$html" ] || bad=1
      grep -q '<script' "$html" 2>/dev/null && bad=1
    done < <(find working/prototypes/dashboard-layout -maxdepth 1 -type f -name 'variant-*.md' 2>/dev/null)
    v1=FAIL; [[ "$n" -eq 3 ]] && v1=PASS
    v2=FAIL; [[ "$n" -eq 3 && "$bad" -eq 0 ]] && v2=PASS
    v3=PASS; [[ -e working/prototypes/dashboard-layout/v1.md ]] && v3=FAIL
    printf '%s\n' \
      "$(emit "Exactly three variant-*.md pages exist at the evaluation storage path, each with a .html export free of <script" "$v1" "found $n variant-*.md pages")" \
      "$(emit "No variant or export holds a script or hand-written HTML" "$v2" "checked each export exists and has no <script> across $n page(s)")" \
      "$(emit "v1.md is absent before direction selection" "$v3" "checked initial round output")" \
      | jq -s '{results: .}'
    ;;
  4)
    root=working/prototypes/profile-panel
    n=0
    [[ ! -d "$root" ]] || n=$(find "$root" -maxdepth 1 -type f -name 'variant-*.md' | wc -l | tr -d ' ')
    v1=FAIL; [[ -f "$root/v1.md" ]] && v1=PASS
    v2=FAIL; [[ "$n" -eq 0 ]] && v2=PASS
    printf '%s\n' \
      "$(emit "v1.md exists for an up-front specific direction" "$v1" "checked $root/v1.md")" \
      "$(emit "No variant pages are generated for an up-front specific direction" "$v2" "found $n variant-*.md pages")" \
      | jq -s '{results: .}'
    ;;
  3)
    expected=working/prototypes/order-cancellation/logic.md
    v=FAIL; e="logic.md missing"
    [[ -f "$expected" ]] && v=PASS && e="logic.md found on disk"
    emit "logic.md exists at the requested evaluation path" "$v" "$e" | jq -s '{results: .}'
    ;;
  *) printf '{"results":[]}' ;;
esac
