#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATOR="$SKILL_DIR/scripts/validate-frontmatter.py"

assertion="The frontmatter name equals the directory name 'deploy-release' (lowercase+hyphens) and is checked with validate-frontmatter.py"
skill_dir="$EVAL_SANDBOX_DIR/deploy-release"
skill_file="$skill_dir/SKILL.md"
verdict=FAIL
evidence="deploy-release/SKILL.md is missing from the workspace"

run_validator() {
  local out
  out="$(UV_PYTHON_PREFERENCE=only-system uv run "$VALIDATOR" --json "$skill_dir" 2>/dev/null)" || true
  if printf '%s' "$out" | jq -e . >/dev/null 2>&1; then
    printf '%s' "$out"
    return 0
  fi
  python3 "$VALIDATOR" --json "$skill_dir"
}

if [ -d "$skill_dir" ] && [ ! -L "$skill_dir" ] && \
   [ -f "$skill_file" ] && [ ! -L "$skill_file" ]; then
  validator_out="$(run_validator)" || true
  if echo "$validator_out" | jq -e '.[0].ok == true' >/dev/null 2>&1; then
    if grep -Eq '^name: *"?deploy-release"?[[:space:]]*$' "$skill_file"; then
      verdict=PASS
      evidence="validate-frontmatter.py passes deploy-release/SKILL.md with name: deploy-release"
    else
      evidence="validate-frontmatter.py passed but frontmatter name is not 'deploy-release'"
    fi
  else
    evidence="validate-frontmatter.py rejected deploy-release/SKILL.md: $validator_out"
  fi
fi

jq -n --arg assertion "$assertion" --arg verdict "$verdict" --arg evidence "$evidence" \
  '{results:[{assertion:$assertion,verdict:$verdict,evidence:$evidence}]}'
