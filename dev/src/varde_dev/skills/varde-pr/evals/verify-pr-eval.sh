#!/usr/bin/env bash
set -euo pipefail
emit() { jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a,verdict:$v,evidence:$e}'; }
skill_dir=$(cd "$(dirname "$0")/.." && pwd)
case "${EVAL_ID:-}" in
  1)
    body=${PR_BODY_FILE:-}
    valid=FAIL; [[ -n "$body" && -f "$body" ]] && "$skill_dir/scripts/check-pr-body.sh" "$body" >/dev/null 2>&1 && valid=PASS
    writes=PASS; [[ ! -s ${GH_LOG:-/dev/null} ]] || grep -Eq '(^|[[:space:]])pr[[:space:]]+(create|edit)([[:space:]]|$)' "$GH_LOG" && writes=FAIL
    printf '%s\n' "$(emit 'Body file exists and passes validation' "$valid" "checked ${body:-unset}")" "$(emit 'No GitHub write command ran' "$writes" "checked ${GH_LOG:-/dev/null}")" | jq -s '{results:.}'
    ;;
  2)
    create=FAIL; bodyfile=FAIL; inline=PASS
    if [[ -s ${GH_LOG:-/dev/null} ]] && grep -Eq '(^|[[:space:]])pr[[:space:]]+create([[:space:]]|$)' "$GH_LOG"; then create=PASS; fi
    if [[ -s ${GH_LOG:-/dev/null} ]] && grep -Eq '(^|[[:space:]])--body-file([=[:space:]]|$)' "$GH_LOG"; then bodyfile=PASS; fi
    if [[ -s ${GH_LOG:-/dev/null} ]] && grep -Eq '(^|[[:space:]])--body(=|[[:space:]]|$)' "$GH_LOG"; then inline=FAIL; fi
    printf '%s\n' "$(emit 'gh pr create ran' "$create" "checked ${GH_LOG:-/dev/null}")" "$(emit 'gh create uses --body-file' "$bodyfile" "checked ${GH_LOG:-/dev/null}")" "$(emit 'gh create does not use inline --body' "$inline" "checked ${GH_LOG:-/dev/null}")" | jq -s '{results:.}'
    ;;
  3)
    body=PASS
    if [[ -n ${PR_OUTPUT_DIR:-} && -d $PR_OUTPUT_DIR ]] && find "$PR_OUTPUT_DIR" -type f -name '*.md' -print -quit | grep -q .; then body=FAIL; fi
    emit 'Review feedback does not create a PR body file' "$body" "checked ${PR_OUTPUT_DIR:-unset}" | jq -s '{results:.}'
    ;;
  *) printf '{"results":[]}\n' ;;
esac
