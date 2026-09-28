#!/usr/bin/env bash
set -euo pipefail

emit() { jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a, verdict:$v, evidence:$e}'; }

case "$EVAL_ID" in
  1)
    note=""
    if [[ -d memory-bank/knowledge/decision ]]; then
      note=$(find memory-bank/knowledge/decision -maxdepth 1 -name '*.md' -print |
        LC_ALL=C sort | sed -n '1p')
    fi
    v1=FAIL; [ -n "$note" ] && v1=PASS
    v2=FAIL
    if [ -n "$note" ]; then
      grep -Eq '^type:[[:space:]]*decision[[:space:]]*$' "$note" &&
        grep -Eq '^description:' "$note" &&
        grep -Eq '^generated:.*by:.*at:' "$note" && v2=PASS
    fi
    v3=FAIL
    if [ -n "$note" ]; then
      grep -Fq '## What' "$note" && grep -Fq '## Why' "$note" &&
        grep -Fq '## Constraints' "$note" && v3=PASS
    fi
    v4=FAIL
    if [ -n "$note" ]; then
      case "$(basename "$note")" in index.md|log.md) v4=FAIL ;; *) v4=PASS ;; esac
    fi
    printf '%s\n' \
      "$(emit "The note is written to memory-bank/knowledge/decision/<slug>.md, with type as a top-level folder" "$v1" "found: ${note:-none}")" \
      "$(emit "Frontmatter includes a non-empty type field, a description, and a generated entry with by and at" "$v2" "checked type/description/generated fields")" \
      "$(emit "The decision body uses the ## What / ## Why / ## Constraints structure" "$v3" "checked for the three headings")" \
      "$(emit "The filename is not index.md or log.md" "$v4" "filename: $(basename "${note:-none}")")" \
      | jq -s '{results: .}'
    ;;
  2)
    f="evals/fixtures/knowledge/pattern/error-envelope.md"
    v1=FAIL; [ -f "$f" ] && grep -Eq '^verified:.*by:[[:space:]]*human:.*at:' "$f" && v1=PASS
    v2=FAIL; [ -f "$f" ] && grep -Fq 'generated: { by: codex/gpt-5, at: 2026-06-01T00:00:00Z }' "$f" && v2=PASS
    printf '%s\n' \
      "$(emit "A verified: { by: human:<id>, at: ... } entry is added to the note" "$v1" "checked for a verified frontmatter entry")" \
      "$(emit "The existing generated entry is not modified or replaced" "$v2" "checked the original generated line is unchanged")" \
      | jq -s '{results: .}'
    ;;
  3)
    f="evals/fixtures/knowledge/pattern/legacy-polling.md"
    v1=FAIL; [ -f "$f" ] && grep -Eq '^status:[[:space:]]*deprecated[[:space:]]*$' "$f" && v1=PASS
    v2=FAIL; [ -f "$f" ] && v2=PASS
    printf '%s\n' \
      "$(emit "The note is marked status: deprecated rather than removed with git rm" "$v1" "checked frontmatter status field")" \
      "$(emit "The file remains at evals/fixtures/knowledge/pattern/legacy-polling.md so existing links resolve" "$v2" "file present: $([ -f "$f" ] && echo yes || echo no)")" \
      | jq -s '{results: .}'
    ;;
  8|9)
    # These assertions describe evaluated behavior. Static fixtures cannot
    # verify it; leave them uncovered so the grader judges session evidence.
    printf '{"results":[]}'
    ;;
  *) printf '{"results":[]}' ;;
esac
