#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local expected="$1"
  local file="$2"
  grep -F -- "$expected" "$file" >/dev/null || fail "expected $expected in $file"
}

checksum() {
  local path="$1"
  if [ -d "$path" ]; then
    find "$path" -type f -exec shasum {} \; | LC_ALL=C sort | shasum | awk '{print $1}'
  else
    printf 'absent\n'
  fi
}

test_dry_run() {
  local home="$TEMP_DIR/dry-run-home"
  local output="$TEMP_DIR/dry-run.out"
  mkdir -p "$home/.claude"
  local before
  before="$(checksum "$home/.claude")"
  HOME="$home" "$ROOT_DIR/varde" init --dry-run </dev/null >"$output"
  [ "$before" = "$(checksum "$home/.claude")" ] || fail "dry run changed Claude config"
  assert_contains "$home/.claude/skills" "$output"
  assert_contains "$home/.claude/agents" "$output"
}

test_skill_dry_run_parity() {
  local dry_target="$TEMP_DIR/skills-dry-target"
  local install_target="$TEMP_DIR/skills-install-target"
  local dry_files="$TEMP_DIR/skills-dry-files"
  local installed_files="$TEMP_DIR/skills-installed-files"

  "$ROOT_DIR/skills/install.sh" -d "$dry_target" -f -n |
    sed -n "s|^Would install .* -> $dry_target/||p" |
    LC_ALL=C sort >"$dry_files"
  "$ROOT_DIR/skills/install.sh" -d "$install_target" -f >/dev/null
  find "$install_target" -type f |
    sed "s|^$install_target/||" |
    LC_ALL=C sort >"$installed_files"
  diff -u "$installed_files" "$dry_files" || fail "skill dry run differs from installation"
}

test_no_tty() {
  local home="$TEMP_DIR/no-tty-home"
  local output="$TEMP_DIR/no-tty.out"
  mkdir -p "$home/.claude"
  HOME="$home" "$ROOT_DIR/varde" init </dev/null >"$output"
  [ ! -e "$home/.claude/skills" ] || fail "no-TTY run installed skills"
  [ ! -e "$home/.claude/agents" ] || fail "no-TTY run installed agents"
  assert_contains "varde init --yes" "$output"
}

test_no_tty_without_detected_harnesses() {
  local home="$TEMP_DIR/no-tty-empty-home"
  local output="$TEMP_DIR/no-tty-empty.out"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" init </dev/null >"$output"
  [ ! -e "$home/.claude" ] || fail "no-TTY run created Claude config"
  [ ! -e "$home/.codex" ] || fail "no-TTY run created Codex config"
  [ ! -e "$home/.config/opencode" ] || fail "no-TTY run created OpenCode config"
  assert_contains "varde init --yes" "$output"
}

test_repeated_install_and_foreign_file() {
  local home="$TEMP_DIR/install-home"
  mkdir -p "$home/.claude/skills/foreign"
  mkdir -p "$home/.claude/agents"
  printf 'leave me alone\n' >"$home/.claude/skills/foreign/keep.txt"
  printf 'custom build agent\n' >"$home/.claude/agents/build.md"
  local foreign_before
  local foreign_agent_before
  foreign_before="$(shasum "$home/.claude/skills/foreign/keep.txt" | awk '{print $1}')"
  foreign_agent_before="$(shasum "$home/.claude/agents/build.md" | awk '{print $1}')"
  HOME="$home" "$ROOT_DIR/varde" init --agents claude
  local first
  first="$(checksum "$home/.claude")"
  HOME="$home" "$ROOT_DIR/varde" init --agents claude
  [ "$first" = "$(checksum "$home/.claude")" ] || fail "repeated install changed results"
  [ "$foreign_before" = "$(shasum "$home/.claude/skills/foreign/keep.txt" | awk '{print $1}')" ] || fail "foreign file changed"
  [ "$foreign_agent_before" = "$(shasum "$home/.claude/agents/build.md" | awk '{print $1}')" ] || fail "foreign agent changed"
  assert_contains "varde-managed-agent" "$home/.claude/agents/plan.md"
}

test_list_agents() {
  local output="$TEMP_DIR/list.out"
  "$ROOT_DIR/varde" init --list-agents >"$output"
  [ "$(cat "$output")" = $'claude\ncodex\nopencode' ] || fail "unexpected harness listing"
}

test_listed_agents_are_valid() {
  local home="$TEMP_DIR/listed-agents-home"
  local output="$TEMP_DIR/listed-agent.out"
  mkdir -p "$home"

  while IFS= read -r agent; do
    HOME="$home" "$ROOT_DIR/varde" init --agents "$agent" --dry-run >"$output"
    case "$agent" in
      claude)
        assert_contains "$home/.claude/skills" "$output"
        assert_contains "$home/.claude/agents" "$output"
        ;;
      codex)
        assert_contains "$home/.codex/skills" "$output"
        assert_contains "$home/.codex/agents" "$output"
        ;;
      opencode)
        assert_contains "$home/.config/opencode/skills" "$output"
        assert_contains "$home/.config/opencode/agent" "$output"
        ;;
      *) fail "listed harness lacks target assertions: $agent" ;;
    esac
  done < <("$ROOT_DIR/varde" init --list-agents)
}

test_multi_harness_legacy_prompt_is_batched() {
  local home="$TEMP_DIR/multi-legacy-home"
  local output="$TEMP_DIR/multi-legacy.out"
  mkdir -p "$home/.claude/skills/varde-plan"
  mkdir -p "$home/.codex/skills/varde-plan"
  printf 'claude custom\n' >"$home/.claude/skills/varde-plan/local.txt"
  printf 'codex custom\n' >"$home/.codex/skills/varde-plan/local.txt"

  printf 'y\n' | HOME="$home" "$ROOT_DIR/varde" init \
    --agents claude,codex >"$output"

  [ "$(grep -Fo 'unmarked legacy skill directories?' "$output" | wc -l | tr -d ' ')" = 1 ] ||
    fail "multi-harness migration did not use one prompt"
  [ ! -e "$home/.claude/skills/varde-plan" ] || fail "Claude legacy remains"
  [ ! -e "$home/.codex/skills/varde-plan" ] || fail "Codex legacy remains"

  home="$TEMP_DIR/multi-legacy-decline-home"
  output="$TEMP_DIR/multi-legacy-decline.out"
  mkdir -p "$home/.claude/skills/varde-plan"
  mkdir -p "$home/.codex/skills/varde-plan"
  printf 'claude custom\n' >"$home/.claude/skills/varde-plan/local.txt"
  printf 'codex custom\n' >"$home/.codex/skills/varde-plan/local.txt"

  printf 'n\n' | HOME="$home" "$ROOT_DIR/varde" init \
    --agents claude,codex >"$output"

  [ "$(grep -Fo 'unmarked legacy skill directories?' "$output" | wc -l | tr -d ' ')" = 1 ] ||
    fail "declined migration repeated its prompt"
  assert_contains "claude custom" "$home/.claude/skills/varde-plan/local.txt"
  assert_contains "codex custom" "$home/.codex/skills/varde-plan/local.txt"
}

test_dry_run
test_skill_dry_run_parity
test_no_tty
test_no_tty_without_detected_harnesses
test_repeated_install_and_foreign_file
test_list_agents
test_listed_agents_are_valid
test_multi_harness_legacy_prompt_is_batched

echo "varde init tests passed"
