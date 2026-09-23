#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
cleanup() {
  chmod -R u+rwx "$TEST_ROOT" 2>/dev/null || true
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

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

portable_mode() {
  local source_path="$1" mode
  if mode=$(stat -f '%Lp' "$source_path" 2>/dev/null); then
    printf '%s\n' "$mode"
  else
    stat -c '%a' "$source_path"
  fi
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

if [ -d "$SKILLS_DIR/varde-browser" ]; then
  browser_target="$TEST_ROOT/browser-pack"
  "$SKILLS_DIR/install.sh" -f -d "$browser_target" --pack browser >/dev/null
  [ "$(directory_set "$browser_target")" = "varde-browser" ] ||
    fail "browser pack installed unexpected skills"
  test ! -e "$browser_target/varde-release" ||
    fail "browser pack installed release capability"

  direct_optional_target="$TEST_ROOT/direct-optional"
  "$SKILLS_DIR/install.sh" -f -d "$direct_optional_target" -s varde-browser >/dev/null
  [ "$(directory_set "$direct_optional_target")" = "varde-browser" ] ||
    fail "direct optional selection installed unexpected skills"
fi

shipping_target="$TEST_ROOT/shipping-pack"
"$SKILLS_DIR/install.sh" -f -d "$shipping_target" --pack shipping >/dev/null
[ "$(directory_set "$shipping_target")" = "varde-release" ] ||
  fail "shipping pack installed unexpected skills"
test -f "$shipping_target/varde-release/.varde-managed-skill" ||
  fail "shipping skill lacks ownership marker"
test ! -e "$shipping_target/varde-browser" ||
  fail "shipping pack depends on browser capability"

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

dry_output="$("$SKILLS_DIR"/install.sh -n -f -d "$TEST_ROOT/dry")"
dry_skills="$(printf '%s\n' "$dry_output" | sed -n "s#.* -> $TEST_ROOT/dry/\(varde-[^/]*\)/.*#\1#p" | sort -u)"
[ "$dry_skills" = "$(expected_set)" ] || fail "dry-run destinations differ"

fixture_root="$TEST_ROOT/installer-fixture"
fixture_target="$TEST_ROOT/filtered-target"
mkdir -p "$fixture_root/varde-change/scripts" \
  "$fixture_root/varde-change/evals" \
  "$fixture_root/varde-change/generated-workspace"
cp "$SKILLS_DIR/install.sh" "$fixture_root/install.sh"
printf '%s\n' '# Fixture skill' > "$fixture_root/varde-change/SKILL.md"
printf '%s\n' '#!/usr/bin/env bash' > "$fixture_root/varde-change/scripts/tool.sh"
printf '%s\n' excluded > "$fixture_root/varde-change/evals/unreadable"
printf '%s\n' excluded > "$fixture_root/varde-change/generated-workspace/unreadable"
chmod 751 "$fixture_root/varde-change/scripts"
chmod 750 "$fixture_root/varde-change/scripts/tool.sh"
chmod 000 "$fixture_root/varde-change/evals" \
  "$fixture_root/varde-change/generated-workspace"
"$fixture_root/install.sh" -f -d "$fixture_target" -s varde-change >/dev/null
[ -x "$fixture_target/varde-change/scripts/tool.sh" ] ||
  fail "filtered installation lost executable permissions"
[ "$(portable_mode "$fixture_target/varde-change/scripts")" = 751 ] ||
  fail "filtered installation lost directory permissions"
[ ! -e "$fixture_target/varde-change/evals" ] ||
  fail "filtered installation copied evals"
[ ! -e "$fixture_target/varde-change/generated-workspace" ] ||
  fail "filtered installation copied workspace artifacts"
test -f "$fixture_target/varde-change/$MARKER" ||
  fail "filtered installation omitted ownership marker"
