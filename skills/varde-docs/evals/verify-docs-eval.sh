#!/usr/bin/env bash
set -euo pipefail

verdict=FAIL
case "$EVAL_ID" in
  5)
    if [[ -f code-cli/CHANGELOG.md && ! -e CHANGELOG.md ]] &&
       grep -Fq 'code-cli/CHANGELOG.md' "$EVAL_TRANSCRIPT"; then verdict=PASS; fi
    jq -n --arg verdict "$verdict" \
      '{results:[{assertion:"Includes code-cli/CHANGELOG.md in the module refresh inventory",verdict:$verdict,evidence:"module CHANGELOG exists without a root CHANGELOG; checked transcript inventory"}]}'
    ;;
  6)
    if sed -n '/^covered_paths:/,/^source_hash:/p' memory-bank/knowledge/specs/billing.md |
         grep -Fq 'src/billing/refunds.rs' &&
       git diff --quiet HEAD -- memory-bank/knowledge/specs/architecture.md; then verdict=PASS; fi
    jq -n --arg verdict "$verdict" \
      '{results:[{assertion:"Billing covered_paths includes the new nonignored file",verdict:$verdict,evidence:"checked billing spec and architecture diff"}]}'
    ;;
  7)
    if ! git diff --quiet HEAD -- memory-bank/knowledge/specs/architecture.md &&
       grep -Fq "hash: $(git hash-object --no-filters deployment.toml)" memory-bank/knowledge/specs/architecture.md &&
       grep -Fq 'src/shared/tax.rs' "$EVAL_TRANSCRIPT" &&
       grep -Fq 'src/billing/common.rs' "$EVAL_TRANSCRIPT"; then verdict=PASS; fi
    jq -n --arg verdict "$verdict" \
      '{results:[{assertion:"Architecture is refreshed and the additional write is reported",verdict:$verdict,evidence:"checked architecture diff and classification paths in transcript"}]}'
    ;;
  8)
    if git diff --quiet HEAD -- docs/config-reference.md &&
       grep -Fq 'timeout is 30' "$EVAL_TRANSCRIPT"; then verdict=PASS; fi
    jq -n --arg verdict "$verdict" \
      '{results:[{assertion:"The proposal-only request leaves the document unchanged",verdict:$verdict,evidence:"checked unchanged doc and proposed value in transcript"}]}'
    ;;
  9)
    if grep -Fq 'The default timeout is 30.' docs/config-reference.md &&
       ! git diff --quiet HEAD -- docs/config-reference.md; then verdict=PASS; fi
    jq -n --arg verdict "$verdict" \
      '{results:[{assertion:"Directly requested source-grounded edit is applied",verdict:$verdict,evidence:"checked updated document and tracked diff"}]}'
    ;;
  *) exit 2 ;;
esac
