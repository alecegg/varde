#!/usr/bin/env bash
set -euo pipefail
emit() { jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a, verdict:$v, evidence:$e}'; }
case "$EVAL_ID" in
  4)
    n=0; [[ ! -d working/explanations ]] || n=$(find working/explanations -type f -name '*.html' | wc -l | tr -d ' ')
    plans=0; [[ ! -d working/plans ]] || plans=$(find working/plans -type f | wc -l | tr -d ' ')
    code=0; git status --porcelain -- src | grep -q . && code=1
    v1=PASS; [[ "$n" -eq 0 ]] || v1=FAIL
    v2=PASS; [[ "$plans" -eq 0 ]] || v2=FAIL
    v3=PASS; [[ "$code" -eq 0 ]] || v3=FAIL
    printf '%s\n' "$(emit 'No HTML artifact is written for a chat options comparison' "$v1" "found $n HTML file(s)")" "$(emit 'No plan or task file is created' "$v2" "found $plans plan/task file(s)")" "$(emit 'No source changes are made' "$v3" 'checked git status')" | jq -s '{results: .}' ;;
  6)
    n=0; [[ ! -d working/explanations ]] || n=$(find working/explanations -type f -name '*.html' | wc -l | tr -d ' ')
    v=PASS; [[ "$n" -eq 0 ]] || v=FAIL
    emit 'No explanation artifact is written during an explicit change request' "$v" "found $n HTML file(s)" | jq -s '{results: .}' ;;
  *) printf '{"results":[]}' ;;
esac
