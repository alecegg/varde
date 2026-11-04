#!/usr/bin/env bash
set -euo pipefail

emit() { jq -n --arg assertion "$1" --arg verdict "$2" --arg evidence "$3" '{assertion:$assertion,verdict:$verdict,evidence:$evidence}'; }
transcript=${EVAL_TRANSCRIPT:?missing EVAL_TRANSCRIPT}

case "$EVAL_ID" in
  friction-capture)
    if awk '
      /friction add/ { add = NR }
      /friction list/ && add && NR > add { list = NR }
      /fixture path was missing/ && list && NR > list { found = 1 }
      END { exit !found }
    ' "$transcript"; then
      verdict=PASS
      evidence='transcript shows friction add, then friction list with the recorded evidence'
    else
      verdict=FAIL
      evidence='transcript lacks the ordered friction add and friction list evidence'
    fi
    emit 'Agent records friction and verifies the resulting list' "$verdict" "$evidence"
    ;;
  *) printf '{"results":[]}\n' ;;
esac | jq -s '{results:.}'
