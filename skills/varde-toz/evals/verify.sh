#!/usr/bin/env bash
set -euo pipefail

emit() { jq -n --arg assertion "$1" --arg verdict "$2" --arg evidence "$3" '{assertion:$assertion,verdict:$verdict,evidence:$evidence}'; }
transcript=${EVAL_TRANSCRIPT:?missing EVAL_TRANSCRIPT}
has() { grep -Fq -- "$1" "$transcript"; }
not_has() { ! has "$1"; }

case "$EVAL_ID" in
  handle-query)
    query=FAIL; has 'varde run query --handle toz-handle-query-01' && query=PASS
    rerun=FAIL; not_has 'git status --short' && rerun=PASS
    printf '%s\n' \
      "$(emit 'The ordered tool trace queries handle toz-handle-query-01 before giving the conclusion' "$query" 'checked query command in transcript')" \
      "$(emit 'The trace does not execute git status --short again' "$rerun" 'checked transcript for the captured command')" \
      | jq -s '{results:.}'
    ;;
  batched-script)
    batch=FAIL; has 'varde run run --script' && batch=PASS
    calls=FAIL; has 'vardeToz.exec' && calls=PASS
    printf '%s\n' \
      "$(emit 'The ordered tool trace uses one varde run run --script invocation for both commands' "$batch" 'checked batch invocation in transcript')" \
      "$(emit 'The script retains each command result before filtering and prints status plus capture handle' "$calls" 'checked script body in transcript')" \
      | jq -s '{results:.}'
    ;;
  no-rerun)
    query=FAIL; has 'varde run query --handle toz-handle-no-rerun-03' && query=PASS
    rerun=FAIL; not_has 'find . -type f' && rerun=PASS
    printf '%s\n' \
      "$(emit 'The trace reads captured handle toz-handle-no-rerun-03' "$query" 'checked query command in transcript')" \
      "$(emit 'The trace does not execute find . -type f again' "$rerun" 'checked transcript for the captured command')" \
      | jq -s '{results:.}'
    ;;
  *) printf '{"results":[]}\n' ;;
esac
