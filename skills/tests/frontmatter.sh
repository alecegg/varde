#!/usr/bin/env bash
# Every skill's SKILL.md frontmatter parses and passes the agentskills.io spec.
set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALIDATOR="$SKILLS_DIR/varde-agent-doc-authoring/scripts/validate-frontmatter.py"

if ! command -v uv >/dev/null 2>&1; then
  echo "SKIP: uv not on PATH; frontmatter not validated"
  exit 0
fi

run_validator() {
  # only-system: use the interpreter on PATH, which works under the sandbox.
  UV_PYTHON_PREFERENCE=only-system uv run -q "$VALIDATOR" "$@"
}

run_validator "$SKILLS_DIR"/varde-*/
echo "Frontmatter checks passed."

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
