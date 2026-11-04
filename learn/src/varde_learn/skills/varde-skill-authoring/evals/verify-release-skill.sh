#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"

assertion="The frontmatter name equals the directory name 'deploy-release' (lowercase+hyphens) and passes varde learn check"
skill_dir="$EVAL_SANDBOX_DIR/deploy-release"
skill_file="$skill_dir/SKILL.md"
verdict=FAIL
evidence="deploy-release/SKILL.md is missing from the workspace"

if [ -d "$skill_dir" ] && [ ! -L "$skill_dir" ] && \
   [ -f "$skill_file" ] && [ ! -L "$skill_file" ]; then
  validator_out="$(varde learn check --json "$skill_dir" 2>&1)" || true
  # The check prints one JSON envelope per lint check, then a text FLOW.md line.
  if echo "$validator_out" | grep '^{' | jq -e -s 'any(.[]; .data.results[0].ok? == true)' >/dev/null 2>&1; then
    verdict=PASS
    evidence="varde learn check passes deploy-release/SKILL.md with name: deploy-release"
  else
    evidence="varde learn check rejected deploy-release/SKILL.md: $validator_out"
  fi
fi

jq -n --arg assertion "$assertion" --arg verdict "$verdict" --arg evidence "$evidence" \
  '{results:[{assertion:$assertion,verdict:$verdict,evidence:$evidence}]}'
