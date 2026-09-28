#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/install-catalogue.XXXXXX")"
cleanup() {
  chmod -R u+rwx "$TEST_ROOT" 2>/dev/null || true
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

EXPECTED=()
for skill_manifest in "$SKILLS_DIR"/varde-*/SKILL.md; do
  EXPECTED+=("$(basename "$(dirname "$skill_manifest")")")
done
[ "${#EXPECTED[@]}" -gt 0 ] || { echo "FAIL: no skills found" >&2; exit 1; }
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

dup_target="$TEST_ROOT/dup"
dup_output="$("$SKILLS_DIR/install.sh" -f -d "$dup_target" -s varde-change,varde-change)"
[ "$(printf '%s\n' "$dup_output" | grep -c '^Installed varde-change ->')" -eq 1 ] ||
  fail "-s with duplicate entries installed more than once"

if "$SKILLS_DIR/install.sh" -f -m -d "$TEST_ROOT/reject" >/dev/null 2>&1; then
  fail "-f and -m together were accepted"
fi

# -m preserves a same-named directory it did not mark, and updates one it did.
unowned_managed_target="$TEST_ROOT/unowned-managed"
mkdir -p "$unowned_managed_target/varde-change"
echo keep > "$unowned_managed_target/varde-change/local.txt"
preserve_output="$("$SKILLS_DIR/install.sh" -m -d "$unowned_managed_target" -s varde-change)"
printf '%s\n' "$preserve_output" | grep -Fq "Preserved unowned $unowned_managed_target/varde-change" ||
  fail "-m did not report preserving an unowned dir"
[ "$(cat "$unowned_managed_target/varde-change/local.txt")" = "keep" ] ||
  fail "-m changed an unowned skill dir"

owned_managed_target="$TEST_ROOT/owned-managed"
"$SKILLS_DIR/install.sh" -f -d "$owned_managed_target" -s varde-change >/dev/null
printf 'stale edit\n' >> "$owned_managed_target/varde-change/SKILL.md"
"$SKILLS_DIR/install.sh" -m -d "$owned_managed_target" -s varde-change >/dev/null
cmp -s "$owned_managed_target/varde-change/SKILL.md" "$SKILLS_DIR/varde-change/SKILL.md" ||
  fail "-m did not update a varde-managed dir"

# Without -f or -m, a prompt with no TTY on stdin fails instead of hanging.
notty_target="$TEST_ROOT/notty"
mkdir -p "$notty_target/varde-change"
if "$SKILLS_DIR/install.sh" -d "$notty_target" -s varde-change \
  </dev/null >/dev/null 2>"$TEST_ROOT/notty.err"; then
  fail "install without a TTY and without -f/-m did not fail"
fi
grep -Fq -- "-f or -m" "$TEST_ROOT/notty.err" ||
  fail "no-TTY failure message did not name -f or -m"

notty_partial="$TEST_ROOT/notty-partial"
mkdir -p "$notty_partial/varde-review"
if "$SKILLS_DIR/install.sh" -d "$notty_partial" -s varde-change,varde-review \
  </dev/null >"$TEST_ROOT/notty-partial.out" 2>&1; then
  fail "partial noninteractive skill install returned success"
fi
grep -Fq 'Previously installed: varde-change' "$TEST_ROOT/notty-partial.out" ||
  fail "noninteractive skill refusal omitted prior success"

# A retired skill the installer placed is removed; a same-named directory
# without the marker was not placed by varde and is left alone.
marked_target="$TEST_ROOT/marked"
mkdir -p "$marked_target/varde-diagnose"
printf 'varde-managed-skill\n' > "$marked_target/varde-diagnose/$MARKER"
"$SKILLS_DIR/install.sh" -f -d "$marked_target" </dev/null >/dev/null
test ! -e "$marked_target/varde-diagnose" || fail "marked retired directory remains"

unmarked_target="$TEST_ROOT/unmarked"
mkdir -p "$unmarked_target/varde-diagnose"
printf 'custom\n' > "$unmarked_target/varde-diagnose/local.txt"
before="$(cksum "$unmarked_target/varde-diagnose/local.txt")"
"$SKILLS_DIR/install.sh" -f -d "$unmarked_target" </dev/null >/dev/null
after="$(cksum "$unmarked_target/varde-diagnose/local.txt")"
[ "$before" = "$after" ] || fail "unmarked directory changed"

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
chmod 750 "$fixture_root/varde-change/scripts/tool.sh"
chmod 000 "$fixture_root/varde-change/evals" \
  "$fixture_root/varde-change/generated-workspace"
"$fixture_root/install.sh" -f -d "$fixture_target" -s varde-change >/dev/null
[ -x "$fixture_target/varde-change/scripts/tool.sh" ] ||
  fail "filtered installation lost executable permissions"
[ ! -e "$fixture_target/varde-change/evals" ] ||
  fail "filtered installation copied evals"
[ ! -e "$fixture_target/varde-change/generated-workspace" ] ||
  fail "filtered installation copied workspace artifacts"
test -f "$fixture_target/varde-change/$MARKER" ||
  fail "filtered installation omitted ownership marker"

# A failed file copy must stop the installer before its success message.
mkdir -p "$TEST_ROOT/failing-bin"
cat > "$TEST_ROOT/failing-bin/cp" <<'EOF'
#!/bin/sh
exit 17
EOF
chmod +x "$TEST_ROOT/failing-bin/cp"
if PATH="$TEST_ROOT/failing-bin:$PATH" "$fixture_root/install.sh" -f \
  -d "$TEST_ROOT/copy-failure" -s varde-change >"$TEST_ROOT/copy-failure.out" 2>&1; then
  fail "skill copy failure returned success"
fi
if grep -Fq 'Done.' "$TEST_ROOT/copy-failure.out"; then
  fail "skill copy failure printed success"
fi

# Replacing a managed skill fails after backup: restore that item, retain
# earlier successes, and state the partial result.
rollback_target="$TEST_ROOT/rollback"
mkdir -p "$rollback_target/varde-review" "$TEST_ROOT/move-failure-bin"
printf 'varde-managed-skill\n' >"$rollback_target/varde-review/$MARKER"
printf 'previous review\n' >"$rollback_target/varde-review/local.txt"
cat >"$TEST_ROOT/move-failure-bin/mv" <<'EOF'
#!/usr/bin/env bash
if [ "$2" = "$FAIL_DEST" ] && [ ! -e "$FAIL_ONCE" ]; then
  : >"$FAIL_ONCE"
  exit 17
fi
exec /bin/mv "$@"
EOF
chmod +x "$TEST_ROOT/move-failure-bin/mv"
if FAIL_DEST="$rollback_target/varde-review" FAIL_ONCE="$TEST_ROOT/skill-mv-failed" \
  PATH="$TEST_ROOT/move-failure-bin:$PATH" "$SKILLS_DIR/install.sh" -f \
  -d "$rollback_target" -s varde-change,varde-review >"$TEST_ROOT/rollback.out" 2>&1; then
  fail "failed skill replacement returned success"
fi
[ "$(cat "$rollback_target/varde-review/local.txt")" = 'previous review' ] ||
  fail "failed skill replacement was not restored"
test -f "$rollback_target/varde-change/$MARKER" || fail "earlier skill was lost"
grep -Fq 'Failed to install varde-review' "$TEST_ROOT/rollback.out" ||
  fail "failed skill not named"
grep -Fq 'Previously installed: varde-change' "$TEST_ROOT/rollback.out" ||
  fail "partial skill result not named"

first_failure="$TEST_ROOT/first-failure"
if PATH="$TEST_ROOT/failing-bin:$PATH" "$fixture_root/install.sh" -f \
  -d "$first_failure" -s varde-change >"$TEST_ROOT/first-failure.out" 2>&1; then
  fail "first skill copy failure returned success"
fi
[ ! -e "$first_failure/varde-change" ] || fail "first skill failure left partial destination"

link_source="$TEST_ROOT/canonical"
link_target="$TEST_ROOT/external-skill"
link_destination="$TEST_ROOT/link-destination"
"$SKILLS_DIR/install.sh" -f -d "$link_source" -s varde-change >/dev/null
mkdir -p "$link_target" "$link_destination"
printf 'external content\n' >"$link_target/local.txt"
ln -s "$link_target" "$link_destination/varde-change"
"$SKILLS_DIR/install.sh" -m -d "$link_destination" -s varde-change -l "$link_source" >/dev/null
[ "$(readlink "$link_destination/varde-change")" = "$link_target" ] ||
  fail "-m replaced unowned skill symlink"
"$SKILLS_DIR/install.sh" -f -d "$link_destination" -s varde-change -l "$link_source" >/dev/null
[ "$(readlink "$link_destination/varde-change")" = "$link_source/varde-change" ] ||
  fail "-f did not replace skill symlink"
[ "$(cat "$link_target/local.txt")" = 'external content' ] ||
  fail "skill symlink target was modified"
