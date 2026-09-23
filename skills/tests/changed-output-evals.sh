#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SKILLS_DIR/varde-agent-doc-authoring/scripts/run-changed-output-evals.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

repo="$TEST_ROOT/repo"
mkdir -p "$repo/skills/eligible/evals" \
  "$repo/skills/unchanged/evals" \
  "$repo/skills/no-evals" \
  "$repo/skills/no-skill/evals"
git -C "$repo" init -q
git -C "$repo" config user.email "fixture@example.com"
git -C "$repo" config user.name "Fixture"

printf '%s\n' '# Eligible' > "$repo/skills/eligible/SKILL.md"
printf '%s\n' '{"evals":[]}' > "$repo/skills/eligible/evals/evals.json"
printf '%s\n' '# Unchanged' > "$repo/skills/unchanged/SKILL.md"
printf '%s\n' '{"evals":[]}' > "$repo/skills/unchanged/evals/evals.json"
printf '%s\n' '# Missing evals' > "$repo/skills/no-evals/SKILL.md"
printf '%s\n' '{"evals":[]}' > "$repo/skills/no-skill/evals/evals.json"
git -C "$repo" add skills
git -C "$repo" commit -qm baseline
base="$(git -C "$repo" rev-parse HEAD)"

printf '%s\n' 'Changed eligible instructions.' >> "$repo/skills/eligible/SKILL.md"
printf '%s\n' 'Changed but ineligible.' >> "$repo/skills/no-evals/SKILL.md"
printf '%s\n' '{"evals":[{"id":1}]}' > "$repo/skills/no-skill/evals/evals.json"
git -C "$repo" add skills
git -C "$repo" commit -qm changes
head="$(git -C "$repo" rev-parse HEAD)"

actual="$($RUNNER --repo "$repo" --skills-dir skills \
  --base "$base" --head "$head" --list-only)"
[[ "$actual" == "skills/eligible" ]] || \
  fail "expected only eligible changed skill, got: $actual"

repeat="$($RUNNER --repo "$repo" --skills-dir skills \
  --base "$base" --head "$head" --list-only)"
[[ "$repeat" == "$actual" ]] || fail "selection order changed between runs"

installed="$TEST_ROOT/installed/scripts"
mkdir -p "$installed"
cp "$RUNNER" "$installed/run-changed-output-evals.sh"
cp "$SKILLS_DIR/varde-agent-doc-authoring/scripts/run-output-evals.sh" \
  "$installed/run-output-evals.sh"
chmod +x "$installed/run-changed-output-evals.sh" \
  "$installed/run-output-evals.sh"
installed_actual="$(
  "$installed/run-changed-output-evals.sh" --repo "$repo" \
    --base "$base" --head "$head" --list-only
)"
[[ "$installed_actual" == "skills/eligible" ]] || \
  fail "explicit repo failed outside Git: $installed_actual"

echo "changed output eval fixtures passed"
