#!/usr/bin/env bash
# Installed shared references must be usable by the shipped documentation CLI.
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
SHARED_DIR="$(shared_skills_dir)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/install-shared-files.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if [[ -n "${VARDE_BIN:-}" ]]; then
  VARDE="$VARDE_BIN"
else
  UV_TOOL_DIR="$TEST_ROOT/uv-tools" UV_TOOL_BIN_DIR="$TEST_ROOT/bin" \
    uv tool install --force --from "$REPO_ROOT/app" varde
  VARDE="$TEST_ROOT/bin/varde"
fi

mkdir -p "$TEST_ROOT/home"
HOME="$TEST_ROOT/home" VARDE_CONFIG_DIR="$TEST_ROOT/home/config" VARDE_AGENTS_OPENCODE_VERSION=1 \
  "$VARDE" setup sync --skills-dir "$TEST_ROOT/skills" --agents-dir "$TEST_ROOT/agents" --harnesses none >/dev/null

check_manifest_behavior() {
  case "$1" in
    references/varde-code-cli.md)
      output="$("$VARDE" map --help 2>&1)" || fail "varde map --help failed"
      [[ "$output" == *"Usage: varde map"* ]] || fail "varde map help omitted its command usage"
      ;;
    references/varde-workflow-cli.md)
      output="$("$VARDE" setup paths --json 2>&1)" || fail "varde setup paths failed"
      printf '%s' "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; assert d["root"] and d["working"]'
      ;;
    references/workflow-state.md)
      output="$("$VARDE" plan --help 2>&1)" || fail "varde plan --help failed"
      [[ "$output" == *"Usage: varde plan"* ]] || fail "varde plan help omitted its command usage"
      ;;
    references/review-gates.md | references/options.md | references/report-format.md | references/sentence-style.md)
      output="$("$VARDE" learn check "$2" 2>&1)" || fail "installed $1 failed learn check"
      [[ "$output" == *"0 error(s)"* ]] || fail "installed $1 did not pass learn check"
      ;;
    references/main-agent-replies.md)
      output="$("$VARDE" plan status 2>&1)" || fail "varde plan status failed"
      [[ "$output" == *"**Progress**"* ]] || fail "varde plan status omitted its progress header"
      ;;
    references/TASK-TEMPLATE.md)
      output="$("$VARDE" plan task set --help 2>&1)" || fail "varde plan task set --help failed"
      [[ "$output" == *"Usage: varde plan task set"* ]] || fail "varde plan task set help omitted its command usage"
      ;;
    *) fail "no behavior check for shared reference: $1" ;;
  esac
}

while IFS= read -r line; do
  [ -n "$line" ] || continue
  [[ "$line" != \#* ]] || continue
  rel_path="${line%% *}"
  skills_text="${line#* }"
  [[ "$rel_path" == references/* && "$line" != "$rel_path" && -n "$skills_text" ]] || fail "malformed shared manifest row: $line"
  read -r -a skills <<< "$skills_text"
  for skill in "${skills[@]}"; do
    source_dir="$(skill_dir "$skill")" || fail "manifest names missing skill: $skill"
    [[ ! -e "$source_dir/$rel_path" ]] || fail "$skill shadows shared $rel_path"
    installed="$TEST_ROOT/skills/$skill/$rel_path"
    [ -f "$installed" ] || fail "$skill is missing installed $rel_path"
    "$VARDE" learn check "$installed" >/dev/null || fail "installed reference is rejected by learn check: $skill/$rel_path"
    check_manifest_behavior "$rel_path" "$installed"
  done
done < "$SHARED_DIR/MANIFEST"

echo "install-shared-files: manifest structure and installed shared reference behavior passed."
