#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AUDITOR="$SKILLS_DIR/varde-change/scripts/audit-word-counts.py"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mkdir -p "$TEST_ROOT/current/varde-alpha/references"
mkdir -p "$TEST_ROOT/baseline/varde-alpha/references"
mkdir -p "$TEST_ROOT/current/varde-alpha/assets"
mkdir -p "$TEST_ROOT/baseline/varde-alpha/assets"

printf '%s\n' 'one two three' > "$TEST_ROOT/current/varde-alpha/SKILL.md"
printf '%s\n' 'four five' > "$TEST_ROOT/current/varde-alpha/references/flow.md"
printf '%s\n' 'six seven' > "$TEST_ROOT/current/varde-alpha/assets/TEMPLATE.md"
printf '%s\n' 'ignored words here' > "$TEST_ROOT/current/varde-alpha/README.md"
printf '%s\n' 'one two' > "$TEST_ROOT/baseline/varde-alpha/SKILL.md"
printf '%s\n' 'four five six' > "$TEST_ROOT/baseline/varde-alpha/references/flow.md"
printf '%s\n' 'six' > "$TEST_ROOT/baseline/varde-alpha/assets/TEMPLATE.md"
cat > "$TEST_ROOT/routes.json" <<'JSON'
{
  "schema_version": 1,
  "routes": [
    {
      "id": "alpha-flow",
      "eval_id": 9,
      "required_documents": ["varde-alpha/SKILL.md"],
      "observed_documents": [
        "varde-alpha/SKILL.md",
        "varde-alpha/references/flow.md"
      ]
    }
  ]
}
JSON

python3 "$AUDITOR" \
  --skills-dir "$TEST_ROOT/current" \
  --baseline-skills-dir "$TEST_ROOT/baseline" \
  --path-catalog "$TEST_ROOT/routes.json" \
  --required-path varde-alpha/SKILL.md \
  --observed-path varde-alpha/references/flow.md \
  --output "$TEST_ROOT/audit.json"

jq -e '
  .schema_version == 1 and
  .current.corpus == {files: 3, words: 7} and
  .current.entrypoint == {files: 1, words: 3} and
  .current.reference == {files: 2, words: 4} and
  .current.packages["varde-alpha"] == {files: 3, words: 7} and
  .current.files["varde-alpha/assets/TEMPLATE.md"] == {kind:"reference", words:2} and
  .required_path == {files: ["varde-alpha/SKILL.md"], words: 3} and
  .observed_path == {files: ["varde-alpha/references/flow.md"], words: 2} and
  .routes["alpha-flow"] == {
    eval_id: 9,
    required_path: {files: ["varde-alpha/SKILL.md"], words: 3},
    observed_path: {
      files: ["varde-alpha/SKILL.md", "varde-alpha/references/flow.md"],
      words: 5
    }
  } and
  .comparison.files["varde-alpha/SKILL.md"] == {baseline: 2, current: 3, delta: 1} and
  .comparison.files["varde-alpha/references/flow.md"] == {baseline: 3, current: 2, delta: -1}
' "$TEST_ROOT/audit.json" >/dev/null || fail "unexpected audit output"

if jq -e '.current.files | has("varde-alpha/README.md")' "$TEST_ROOT/audit.json" >/dev/null; then
  fail "README.md should not enter the prompt-document corpus"
fi

if python3 "$AUDITOR" --skills-dir "$TEST_ROOT/current" \
  --required-path varde-alpha/missing.md >/dev/null 2>&1; then
  fail "missing routing paths should fail"
fi

cat > "$TEST_ROOT/invalid-routes.json" <<'JSON'
{"schema_version":1,"routes":[{"id":"bad","eval_id":1,"required_documents":["missing.md"],"observed_documents":[]}]}
JSON
if python3 "$AUDITOR" --skills-dir "$TEST_ROOT/current" \
  --path-catalog "$TEST_ROOT/invalid-routes.json" >/dev/null 2>&1; then
  fail "catalog routes containing missing documents should fail"
fi

echo "word-count audit fixtures passed"
