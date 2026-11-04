#!/usr/bin/env bash
# Every skill's SKILL.md frontmatter parses and passes the agentskills.io spec.
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
export VARDE_CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/frontmatter-config.XXXXXX")"

run_validator() {
  uv run --locked --project "$REPO_ROOT/app" varde learn check "$@"
}

skills=()
while IFS= read -r skill; do skills+=("$skill"); done < <(skill_dirs)
if [ "${#skills[@]}" -eq 0 ]; then
  echo "no skills found" >&2
  exit 1
fi
run_validator "${skills[@]}"
echo "Frontmatter checks passed for ${#skills[@]} skills."

tmp="$(mktemp -d "${TMPDIR:-/tmp}/frontmatter-fixture.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

# Fixture: a whitespace-only description must fail.
mkdir -p "$tmp/blank-description"
cat > "$tmp/blank-description/SKILL.md" <<'EOF'
---
name: blank-description
description: "   "
---
Body.
EOF
if run_validator "$tmp/blank-description" >/dev/null 2>&1; then
  echo "expected whitespace-only description to fail validation" >&2
  exit 1
fi
echo "Whitespace-only description correctly rejected."

# Fixture: a folded block scalar description must fail.
mkdir -p "$tmp/folded-description"
cat > "$tmp/folded-description/SKILL.md" <<'EOF'
---
name: folded-description
description: >
  A description written as a folded block scalar.
---
Body.
EOF
if run_validator "$tmp/folded-description" >/dev/null 2>&1; then
  echo "expected folded block scalar description to fail validation" >&2
  exit 1
fi
echo "Folded block scalar description correctly rejected."
