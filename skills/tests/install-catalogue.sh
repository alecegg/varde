#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

EXPECTED=(
  varde-agent-doc-authoring
  varde-change
  varde-docs
  varde-explore
  varde-knowledge
  varde-prototype
  varde-review
)
MARKER=.varde-managed-skill

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

directory_set() {
  find "$1" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
}

expected_set() {
  printf '%s\n' "${EXPECTED[@]}" | sort
}

clean_target="$TEST_ROOT/clean"
"$SKILLS_DIR/install.sh" -f -d "$clean_target" >/dev/null
[ "$(directory_set "$clean_target")" = "$(expected_set)" ] ||
  fail "default installation differs from seven-skill manifest"
for skill in "${EXPECTED[@]}"; do
  test -f "$clean_target/$skill/$MARKER" || fail "$skill lacks ownership marker"
done
if find "$clean_target" -type d -name evals | grep -q .; then
  fail "installed skills contain author-only evaluation directories"
fi

subset_target="$TEST_ROOT/subset"
"$SKILLS_DIR/install.sh" -f -d "$subset_target" -s varde-change,varde-review >/dev/null
[ "$(directory_set "$subset_target")" = $'varde-change\nvarde-review' ] ||
  fail "explicit selection installed unexpected skills"
if "$SKILLS_DIR/install.sh" -f -d "$subset_target" \
  -s 'varde-change varde-review' >/dev/null 2>&1; then
  fail "combined invalid selection was accepted"
fi

marked_target="$TEST_ROOT/marked"
mkdir -p "$marked_target/varde-plan"
printf 'varde-managed-skill\n' > "$marked_target/varde-plan/$MARKER"
"$SKILLS_DIR/install.sh" --yes -f -d "$marked_target" >/dev/null
test ! -e "$marked_target/varde-plan" || fail "marked retired directory remains"

declined_target="$TEST_ROOT/declined"
mkdir -p "$declined_target/varde-plan"
printf 'custom\n' > "$declined_target/varde-plan/local.txt"
before="$(cksum "$declined_target/varde-plan/local.txt")"
printf 'n\n' | "$SKILLS_DIR/install.sh" -f -d "$declined_target" >/dev/null
after="$(cksum "$declined_target/varde-plan/local.txt")"
[ "$before" = "$after" ] || fail "declined legacy directory changed"

accepted_target="$TEST_ROOT/accepted"
mkdir -p "$accepted_target/varde-plan"
printf 'custom\n' > "$accepted_target/varde-plan/local.txt"
printf 'y\n' | "$SKILLS_DIR/install.sh" -f -d "$accepted_target" >/dev/null
test ! -e "$accepted_target/varde-plan" || fail "accepted legacy directory remains"

yes_target="$TEST_ROOT/yes"
mkdir -p "$yes_target/varde-plan" "$yes_target/unrelated"
printf 'custom\n' > "$yes_target/varde-plan/local.txt"
printf 'keep\n' > "$yes_target/unrelated/local.txt"
"$SKILLS_DIR/install.sh" --yes -f -d "$yes_target" </dev/null >/dev/null
test ! -e "$yes_target/varde-plan" || fail "--yes preserved legacy directory"
grep -F keep "$yes_target/unrelated/local.txt" >/dev/null ||
  fail "unrelated directory changed"

dry_output="$($SKILLS_DIR/install.sh -n -f -d "$TEST_ROOT/dry")"
dry_skills="$(printf '%s\n' "$dry_output" | sed -n "s#.* -> $TEST_ROOT/dry/\(varde-[^/]*\)/.*#\1#p" | sort -u)"
[ "$dry_skills" = "$(expected_set)" ] || fail "dry-run destinations differ"
