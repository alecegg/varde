#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/varde-sync.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

# Exclude the real toz binary (e.g. ~/.cargo/bin/toz) so every sync
# invocation below is toz-absent unless a stub dir is prepended to PATH.
# Wiring fixtures use --no-cli; agents/tests/sync-cli-install.sh covers installs.
SAFE_PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export PATH="$SAFE_PATH"

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

make_toz_stub() {
  local stub_dir="$1"
  local log="$2"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/toz" <<STUB
#!/bin/sh
echo "\$@" >> "$log"
STUB
  chmod +x "$stub_dir/toz"
}

make_workflow_stub() {
  local stub_dir="$1"
  local log="$2"
  local toz_json="$3"
  local set_exit="${4:-0}"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/varde-workflow" <<STUB
#!/bin/sh
if [ "\$1" = "paths" ] && [ "\$2" = "--json" ]; then
  printf '%s\n' '{"data":{"toz":$toz_json,"toz_source":null}}'
  exit 0
fi
if [ "\$1" = "paths" ] && [ "\$2" = "set" ]; then
  echo "\$@" >> "$log"
  exit $set_exit
fi
exit 1
STUB
  chmod +x "$stub_dir/varde-workflow"
}

make_workflow_stub_paths_failing() {
  local stub_dir="$1"
  local log="$2"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/varde-workflow" <<STUB
#!/bin/sh
if [ "\$1" = "paths" ] && [ "\$2" = "--json" ]; then
  exit 1
fi
if [ "\$1" = "paths" ] && [ "\$2" = "set" ]; then
  echo "\$@" >> "$log"
  exit 0
fi
exit 1
STUB
  chmod +x "$stub_dir/varde-workflow"
}

make_workflow_stub_paths_bad_json() {
  local stub_dir="$1"
  local log="$2"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/varde-workflow" <<STUB
#!/bin/sh
if [ "\$1" = "paths" ] && [ "\$2" = "--json" ]; then
  printf 'not json\n'
  exit 0
fi
if [ "\$1" = "paths" ] && [ "\$2" = "set" ]; then
  echo "\$@" >> "$log"
  exit 0
fi
exit 1
STUB
  chmod +x "$stub_dir/varde-workflow"
}

test_dry_run() {
  local home="$TEMP_DIR/dry-run-home"
  local output="$TEMP_DIR/dry-run.out"
  mkdir -p "$home/.claude"
  local before
  before="$(checksum "$home/.claude")"
  HOME="$home" "$ROOT_DIR/varde" sync --dry-run </dev/null >"$output"
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
  local rc=0
  mkdir -p "$home/.claude"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli </dev/null >"$output" || rc=$?
  [ "$rc" -eq 1 ] || fail "no-TTY run should exit 1, got $rc"
  [ ! -e "$home/.claude/skills" ] || fail "no-TTY run installed skills"
  [ ! -e "$home/.claude/agents" ] || fail "no-TTY run installed agents"
  assert_contains "varde sync --yes" "$output"
}

test_no_tty_without_detected_harnesses() {
  local home="$TEMP_DIR/no-tty-empty-home"
  local output="$TEMP_DIR/no-tty-empty.out"
  local rc=0
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli </dev/null >"$output" || rc=$?
  [ "$rc" -eq 1 ] || fail "no-TTY run should exit 1, got $rc"
  [ ! -e "$home/.claude" ] || fail "no-TTY run created Claude config"
  [ ! -e "$home/.codex" ] || fail "no-TTY run created Codex config"
  [ ! -e "$home/.config/opencode" ] || fail "no-TTY run created OpenCode config"
  assert_contains "varde sync --yes" "$output"
}

test_unmarked_skill_dir_preserved_by_yes() {
  local home="$TEMP_DIR/unmarked-skill-home"
  mkdir -p "$home/.claude/skills/varde-foreign"
  printf 'not managed by varde\n' >"$home/.claude/skills/varde-foreign/keep.txt"
  local before
  before="$(shasum "$home/.claude/skills/varde-foreign/keep.txt" | awk '{print $1}')"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --yes >/dev/null
  [ "$before" = "$(shasum "$home/.claude/skills/varde-foreign/keep.txt" | awk '{print $1}')" ] ||
    fail "unmarked varde-* skill dir was overwritten"
}

test_custom_skills_dir_installs_there() {
  local home="$TEMP_DIR/custom-skills-home"
  local target="$TEMP_DIR/custom-skills-target"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --skills-dir "$target" --yes >/dev/null
  [ -d "$target/varde-change" ] || fail "--skills-dir did not install skills into custom target"
  [ -d "$home/.claude/skills/varde-change" ] || fail "--skills-dir should not replace detected harness install"
}

test_shared_skill_links() {
  local home="$TEMP_DIR/shared-skills-home"
  local custom_target="$TEMP_DIR/shared-skills-custom-target"
  local target
  mkdir -p "$home/.claude/skills/varde-change" "$home/.codex" "$home/.config/opencode"
  printf 'varde-managed-skill\n' >"$home/.claude/skills/varde-change/.varde-managed-skill"
  printf 'old copy\n' >"$home/.claude/skills/varde-change/SKILL.md"

  HOME="$home" "$ROOT_DIR/varde" sync --agents claude,codex,opencode \
    --skills-dir "$custom_target" --no-cli --yes >/dev/null

  [ -d "$home/.agents/skills/varde-change" ] || fail "canonical skill missing"
  [ ! -L "$home/.agents/skills/varde-change" ] || fail "canonical skill is a symlink"
  [ -f "$home/.agents/skills/varde-change/.varde-managed-skill" ] ||
    fail "canonical skill lacks ownership marker"
  [ -f "$home/.agents/skills/varde-review/SKILL.md" ] ||
    fail "canonical varde-review skill missing"
  [ -f "$home/.agents/skills/varde-review/references/report.md" ] ||
    fail "canonical varde-review report workflow missing"
  [ -f "$home/.agents/skills/varde-review/references/fix.md" ] ||
    fail "canonical varde-review fix workflow missing"
  for target in "$home/.claude/skills" "$home/.codex/skills" \
    "$home/.config/opencode/skills" "$custom_target"; do
    [ -L "$target/varde-change" ] || fail "skill in $target is not linked"
    [ "$(readlink "$target/varde-change")" = "$home/.agents/skills/varde-change" ] ||
      fail "skill in $target points to wrong source"
    [ -L "$target/varde-review" ] || fail "varde-review in $target is not linked"
    [ "$(readlink "$target/varde-review")" = "$home/.agents/skills/varde-review" ] ||
      fail "varde-review in $target points to wrong source"
  done
}

test_retired_skill_links_removed() {
  local home="$TEMP_DIR/retired-links-home"
  mkdir -p "$home/.agents/skills/varde-release" "$home/.claude/skills"
  printf 'varde-managed-skill\n' >"$home/.agents/skills/varde-release/.varde-managed-skill"
  ln -s "$home/.agents/skills/varde-release" "$home/.claude/skills/varde-release"

  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null

  [ ! -e "$home/.agents/skills/varde-release" ] || fail "retired canonical skill kept"
  [ ! -L "$home/.claude/skills/varde-release" ] || fail "retired skill link kept"
}

test_custom_agents_dir_requires_format() {
  local home="$TEMP_DIR/custom-agents-no-format-home"
  local output="$TEMP_DIR/custom-agents-no-format.out"
  local rc=0
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents-dir "$TEMP_DIR/custom-agents-target" --yes \
    >"$output" 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || fail "--agents-dir without --agent-format should exit non-zero"
}

test_custom_agents_dir_installs_format() {
  local home="$TEMP_DIR/custom-agents-home"
  local target="$TEMP_DIR/custom-agents-target"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents-dir "$target" --agent-format codex --yes \
    >/dev/null
  ls "$target"/*.toml >/dev/null 2>&1 || fail "--agents-dir --agent-format codex did not install .toml agents"
}

test_toz_install_when_present() {
  local home="$TEMP_DIR/toz-present-home"
  local stub_dir="$TEMP_DIR/toz-present-stub"
  local log="$TEMP_DIR/toz-present.log"
  mkdir -p "$home"
  make_toz_stub "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  assert_contains "install claude-code" "$log"
}

test_toz_dry_run_when_present() {
  local home="$TEMP_DIR/toz-dry-home"
  local stub_dir="$TEMP_DIR/toz-dry-stub"
  local log="$TEMP_DIR/toz-dry.log"
  local output="$TEMP_DIR/toz-dry.out"
  mkdir -p "$home"
  make_toz_stub "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --dry-run --agents claude >"$output"
  assert_contains "would run: toz install claude-code" "$output"
  [ ! -s "$log" ] || fail "dry run invoked the toz stub"
}

test_toz_absent() {
  local home="$TEMP_DIR/toz-absent-home"
  local output="$TEMP_DIR/toz-absent.out"
  local rc=0
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || fail "toz-absent run should exit 0, got $rc"
  assert_contains "cargo install --path" "$output"
  assert_contains "clis/toz/crates/toz" "$output"
}

test_learn_cli_dry_run_prints_install_line() {
  local home="$TEMP_DIR/learn-cli-dry-home"
  local output="$TEMP_DIR/learn-cli-dry.out"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --dry-run --agents claude >"$output"
  assert_contains "would run: cargo install --path $ROOT_DIR/clis/learn/crates/varde-learn --locked --force --target-dir $ROOT_DIR/clis/learn/target" "$output"
}

test_no_cli_warns_varde_learn_missing() {
  local home="$TEMP_DIR/no-cli-learn-home"
  local output="$TEMP_DIR/no-cli-learn.out"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --agents claude --no-cli --yes >"$output"
  assert_contains "varde-learn not found; install it with: cargo install --path $ROOT_DIR/clis/learn/crates/varde-learn --locked --target-dir $ROOT_DIR/clis/learn/target" "$output"
}

test_toz_store_set_when_unset() {
  local home="$TEMP_DIR/toz-store-unset-home"
  local stub_dir="$TEMP_DIR/toz-store-unset-stub"
  local log="$TEMP_DIR/toz-store-unset.log"
  mkdir -p "$home"
  make_workflow_stub "$stub_dir" "$log" "null"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME= "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  assert_contains "--default --toz $home/.config/varde-toz" "$log"
}

test_toz_store_uses_xdg_config_home() {
  local home="$TEMP_DIR/toz-store-xdg-home"
  local xdg_config="$TEMP_DIR/toz-store-xdg-config"
  local stub_dir="$TEMP_DIR/toz-store-xdg-stub"
  local log="$TEMP_DIR/toz-store-xdg.log"
  mkdir -p "$home" "$xdg_config"
  make_workflow_stub "$stub_dir" "$log" "null"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME="$xdg_config" \
    "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  assert_contains "--default --toz $xdg_config/varde-toz" "$log"
}

test_toz_store_preserves_legacy_default() {
  local home="$TEMP_DIR/toz-store-legacy-home"
  local stub_dir="$TEMP_DIR/toz-store-legacy-stub"
  local log="$TEMP_DIR/toz-store-legacy.log"
  mkdir -p "$home/.config/tool-output-zone"
  make_workflow_stub "$stub_dir" "$log" "null"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME= \
    "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  assert_contains "--default --toz $home/.config/tool-output-zone" "$log"
}

test_toz_store_uses_canonical_alias_target() {
  local home="$TEMP_DIR/toz-store-alias-home"
  local stub_dir="$TEMP_DIR/toz-store-alias-stub"
  local log="$TEMP_DIR/toz-store-alias.log"
  mkdir -p "$home/.config/varde-toz"
  ln -s "$home/.config/varde-toz" "$home/.config/tool-output-zone"
  make_workflow_stub "$stub_dir" "$log" "null"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME= \
    "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  assert_contains "--default --toz $home/.config/varde-toz" "$log"
}

test_toz_store_not_set_when_present() {
  local home="$TEMP_DIR/toz-store-set-home"
  local stub_dir="$TEMP_DIR/toz-store-set-stub"
  local log="$TEMP_DIR/toz-store-set.log"
  mkdir -p "$home"
  make_workflow_stub "$stub_dir" "$log" "\"$home/.config/tool-output-zone\""
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null
  [ ! -s "$log" ] || fail "paths set should not run when toz store is already set"
}

test_toz_store_dry_run() {
  local home="$TEMP_DIR/toz-store-dry-home"
  local stub_dir="$TEMP_DIR/toz-store-dry-stub"
  local log="$TEMP_DIR/toz-store-dry.log"
  local output="$TEMP_DIR/toz-store-dry.out"
  mkdir -p "$home"
  make_workflow_stub "$stub_dir" "$log" "null"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME= "$ROOT_DIR/varde" sync --dry-run --agents claude >"$output"
  assert_contains "would run: varde-workflow paths set --default --toz $home/.config/varde-toz" "$output"
  [ ! -s "$log" ] || fail "dry run invoked paths set"
}

test_toz_store_set_failure_prints_hint() {
  local home="$TEMP_DIR/toz-store-fail-home"
  local stub_dir="$TEMP_DIR/toz-store-fail-stub"
  local log="$TEMP_DIR/toz-store-fail.log"
  local output="$TEMP_DIR/toz-store-fail.out"
  local rc=0
  mkdir -p "$home"
  make_workflow_stub "$stub_dir" "$log" "null" 1
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" XDG_CONFIG_HOME= "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || fail "sync should exit 0 even when paths set fails, got $rc"
  assert_contains "could not set default toz store; run: varde-workflow paths set --default --toz $home/.config/varde-toz" "$output"
}

test_toz_store_paths_read_failure_skips() {
  local home="$TEMP_DIR/toz-store-paths-fail-home"
  local stub_dir="$TEMP_DIR/toz-store-paths-fail-stub"
  local log="$TEMP_DIR/toz-store-paths-fail.log"
  local output="$TEMP_DIR/toz-store-paths-fail.out"
  local rc=0
  mkdir -p "$home"
  make_workflow_stub_paths_failing "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || fail "sync should exit 0 even when paths --json fails, got $rc"
  [ ! -s "$log" ] || fail "paths set should not run when paths --json exits non-zero"
  assert_contains "could not read varde paths; skipping default toz store" "$output"
}

test_toz_store_paths_bad_json_skips() {
  local home="$TEMP_DIR/toz-store-bad-json-home"
  local stub_dir="$TEMP_DIR/toz-store-bad-json-stub"
  local log="$TEMP_DIR/toz-store-bad-json.log"
  local output="$TEMP_DIR/toz-store-bad-json.out"
  local rc=0
  mkdir -p "$home"
  make_workflow_stub_paths_bad_json "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || fail "sync should exit 0 even when paths --json output is unparseable, got $rc"
  [ ! -s "$log" ] || fail "paths set should not run when paths --json output is unparseable"
  assert_contains "could not read varde paths; skipping default toz store" "$output"
}

test_only_custom_targets_skip_detected_harnesses() {
  local home="$TEMP_DIR/only-custom-home"
  local skills_target="$TEMP_DIR/only-custom-skills-target"
  mkdir -p "$home/.claude"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --skills-dir "$skills_target" --yes >/dev/null
  [ -d "$skills_target/varde-change" ] || fail "--skills-dir alone did not install"
  [ ! -e "$home/.claude/skills" ] || fail "custom-only run should skip detected harness writes"
  [ ! -e "$home/.claude/agents" ] || fail "custom-only run should skip detected harness writes"
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
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude
  local first
  first="$(checksum "$home/.claude")"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude
  [ "$first" = "$(checksum "$home/.claude")" ] || fail "repeated install changed results"
  [ "$foreign_before" = "$(shasum "$home/.claude/skills/foreign/keep.txt" | awk '{print $1}')" ] || fail "foreign file changed"
  [ "$foreign_agent_before" = "$(shasum "$home/.claude/agents/build.md" | awk '{print $1}')" ] || fail "foreign agent changed"
  assert_contains "varde-managed-agent" "$home/.claude/agents/varde-planner.md"
}

test_list_agents() {
  local output="$TEMP_DIR/list.out"
  "$ROOT_DIR/varde" sync --list-agents >"$output"
  [ "$(cat "$output")" = $'claude\ncodex\nopencode\npi' ] || fail "unexpected harness listing"
}

test_listed_agents_are_valid() {
  local home="$TEMP_DIR/listed-agents-home"
  local output="$TEMP_DIR/listed-agent.out"
  mkdir -p "$home"

  while IFS= read -r agent; do
    HOME="$home" "$ROOT_DIR/varde" sync --agents "$agent" --dry-run >"$output"
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
        assert_contains "$home/.config/opencode/agents" "$output"
        ;;
      pi)
        assert_contains "$home/.pi/agent/agents" "$output"
        ;;
      *) fail "listed harness lacks target assertions: $agent" ;;
    esac
  done < <("$ROOT_DIR/varde" sync --list-agents)
}

test_install_preserves_harness_startup_config() {
  local home="$TEMP_DIR/startup-config-home"
  local output="$TEMP_DIR/startup-config.out"
  mkdir -p "$home/.claude" "$home/.codex" "$home/.config/opencode/plugin"
  printf '{"custom": true}\n' >"$home/.claude/settings.json"
  printf 'custom = true\n' >"$home/.codex/config.toml"
  printf 'export const custom = true;\n' >"$home/.config/opencode/plugin/custom.js"

  local claude_before
  local codex_before
  local opencode_before
  claude_before="$(shasum "$home/.claude/settings.json" | awk '{print $1}')"
  codex_before="$(shasum "$home/.codex/config.toml" | awk '{print $1}')"
  opencode_before="$(shasum "$home/.config/opencode/plugin/custom.js" | awk '{print $1}')"

  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude,codex,opencode >"$output"

  [ "$claude_before" = "$(shasum "$home/.claude/settings.json" | awk '{print $1}')" ] ||
    fail "Claude startup configuration changed"
  [ "$codex_before" = "$(shasum "$home/.codex/config.toml" | awk '{print $1}')" ] ||
    fail "Codex startup configuration changed"
  [ "$opencode_before" = "$(shasum "$home/.config/opencode/plugin/custom.js" | awk '{print $1}')" ] ||
    fail "OpenCode startup configuration changed"
  [ ! -e "$home/.config/opencode/plugin/varde-advisory-bootstrap.js" ] ||
    fail "OpenCode advisory bootstrap was installed"
}

make_hook_stubs() {
  local stub_dir="$1"
  local log="$2"
  local skipped="${3:-false}"
  local instruction_targets="${4:-}"
  mkdir -p "$stub_dir"
  cat >"$stub_dir/varde-code" <<STUB
#!/bin/sh
echo "varde-code \$@" >> "$log"
printf '%s\n' '{"data":{"removed":[{"skippedModified":$skipped}]}}'
STUB
  cat >"$stub_dir/varde-workflow" <<STUB
#!/bin/sh
if [ "\$1" = "paths" ] && [ "\$2" = "--json" ]; then
  printf '%s\n' '{"data":{"toz":"x"}}'
  exit 0
fi
if [ "\$1" = "instructions" ] && [ "\$2" = "targets" ]; then
  [ -z "$instruction_targets" ] || printf '%s\n' "$instruction_targets"
  exit 0
fi
if [ "\$1" = "instructions" ] && [ "\$2" = "install" ]; then
  echo "varde-workflow \$@" >> "$log"
  if [ "\$#" -eq 2 ]; then
    printf '%s\n' 'Varde will not work as designed until its instruction block is installed: agents will not delegate as designed or use toz captures. Install it with \`varde-workflow instructions install --target <file>\`. Use one canonical \`AGENTS.md\` symlinked into each harness.'
  fi
  exit 0
fi
echo "varde-workflow \$@" >> "$log"
STUB
  chmod +x "$stub_dir/varde-code" "$stub_dir/varde-workflow"
}

test_instructions_install_for_configured_targets() {
  local home="$TEMP_DIR/instructions-configured-home"
  local stub_dir="$TEMP_DIR/instructions-configured-stub"
  local log="$TEMP_DIR/instructions-configured.log"
  local target="$TEMP_DIR/shared-instructions/AGENTS.md"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log" false "$target"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >/dev/null

  local hook_line install_line
  hook_line="$(line_of "varde-workflow hook install --harness claude" "$log")"
  install_line="$(line_of "varde-workflow instructions install" "$log")"
  [ -n "$hook_line" ] || fail "missing hook install before instruction block install"
  [ -n "$install_line" ] || fail "configured instruction target was not installed"
  [ "$hook_line" -lt "$install_line" ] || fail "instruction block install must follow per-harness wiring"
}

test_instructions_warn_without_targets_under_yes() {
  local home="$TEMP_DIR/instructions-yes-home"
  local stub_dir="$TEMP_DIR/instructions-yes-stub"
  local log="$TEMP_DIR/instructions-yes.log"
  local output="$TEMP_DIR/instructions-yes.out"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output"

  assert_contains "Varde will not work as designed until its instruction block is installed:" "$output"
  assert_contains "varde-workflow instructions install --target <file>" "$output"
}

test_instructions_dry_run_prints_install_command() {
  local home="$TEMP_DIR/instructions-dry-home"
  local stub_dir="$TEMP_DIR/instructions-dry-stub"
  local log="$TEMP_DIR/instructions-dry.log"
  local output="$TEMP_DIR/instructions-dry.out"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --dry-run --agents claude >"$output"

  assert_contains "would run: varde-workflow instructions install" "$output"
  [ ! -s "$log" ] || fail "dry run executed an instruction install command"
}

test_prompted_home_targets_expand_tilde() {
  local home="$TEMP_DIR/instructions-tilde-home"
  local stub_dir="$TEMP_DIR/instructions-tilde-stub"
  local log="$TEMP_DIR/instructions-tilde.log"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log"

  python3 - "$ROOT_DIR/varde" "$stub_dir" "$home" <<'PY'
import os
import pty
import select
import subprocess
import sys

master, slave = pty.openpty()
env = os.environ.copy()
env.update({"PATH": f"{sys.argv[2]}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": sys.argv[3]})
process = subprocess.Popen(
    [sys.argv[1], "sync", "--no-cli", "--agents", "claude"],
    stdin=slave,
    stdout=slave,
    stderr=slave,
    env=env,
    close_fds=True,
)
os.close(slave)
os.write(master, b"~/AGENTS.md\n")
while process.poll() is None:
    ready, _, _ = select.select([master], [], [], 0.1)
    if ready:
        try:
            os.read(master, 4096)
        except OSError:
            break
status = process.wait()
os.close(master)
sys.exit(status)
PY

  assert_contains "varde-workflow instructions install --target $home/AGENTS.md" "$log"
  [ "$(grep -cF 'varde-workflow instructions install' "$log")" -eq 1 ] ||
    fail "prompted instruction install should run exactly once"
}

test_session_hook_remove_then_install() {
  local home="$TEMP_DIR/hook-home"
  local stub_dir="$TEMP_DIR/hook-stub"
  local log="$TEMP_DIR/hook.log"
  local agent
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude,codex,opencode --yes >/dev/null
  for agent in claude codex opencode; do
    local remove_line install_line
    remove_line="$(grep -nF -- "varde-code hooks remove --agent $agent" "$log" | head -1 | cut -d: -f1)"
    install_line="$(grep -nF -- "varde-workflow hook install --harness $agent" "$log" | head -1 | cut -d: -f1)"
    [ -n "$remove_line" ] || fail "missing hooks remove for $agent"
    [ -n "$install_line" ] || fail "missing hook install for $agent"
    [ "$remove_line" -lt "$install_line" ] || fail "hooks remove must precede hook install for $agent"
  done
}

test_session_hook_dry_run() {
  local home="$TEMP_DIR/hook-dry-home"
  local stub_dir="$TEMP_DIR/hook-dry-stub"
  local log="$TEMP_DIR/hook-dry.log"
  local output="$TEMP_DIR/hook-dry.out"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --dry-run --agents claude,codex >"$output"
  assert_contains "would run: varde-code hooks remove --agent codex" "$output"
  assert_contains "would run: varde-workflow hook install --harness codex" "$output"
  [ ! -s "$log" ] || fail "dry run executed hook commands"
}

test_session_hook_reports_skipped_modified() {
  local home="$TEMP_DIR/hook-skip-home"
  local stub_dir="$TEMP_DIR/hook-skip-stub"
  local log="$TEMP_DIR/hook-skip.log"
  local output="$TEMP_DIR/hook-skip.out"
  mkdir -p "$home"
  make_hook_stubs "$stub_dir" "$log" true
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents claude --yes >"$output"
  assert_contains "skipped locally modified claude entries" "$output"
}

make_pi_stubs() {
  local stub_dir="$1"
  local log="$2"
  make_hook_stubs "$stub_dir" "$log"
  cat >"$stub_dir/varde-toz" <<STUB
#!/bin/sh
echo "varde-toz \$@" >> "$log"
STUB
  chmod +x "$stub_dir/varde-toz"
}

line_of() {
  grep -nF -- "$1" "$2" | head -1 | cut -d: -f1
}

test_pi_sync_order_and_no_skills_link() {
  local home="$TEMP_DIR/pi-home"
  local stub_dir="$TEMP_DIR/pi-stub"
  local log="$TEMP_DIR/pi.log"
  mkdir -p "$home/.pi"
  make_pi_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --yes >/dev/null
  local toz_line remove_line install_line
  toz_line="$(line_of "varde-toz install pi" "$log")"
  remove_line="$(line_of "varde-code hooks remove --agent pi" "$log")"
  install_line="$(line_of "varde-workflow hook install --harness pi" "$log")"
  [ -n "$toz_line" ] && [ -n "$remove_line" ] && [ -n "$install_line" ] || fail "missing pi wiring call"
  [ "$toz_line" -lt "$remove_line" ] && [ "$remove_line" -lt "$install_line" ] ||
    fail "pi calls must run toz, hooks remove, hook install in order"
  [ -f "$home/.pi/agent/agents/varde-executor.md" ] || fail "pi agents were not installed"
  [ ! -e "$home/.pi/agent/skills" ] || fail "pi skills were linked"
  [ -d "$home/.agents/skills" ] || fail "canonical skills missing"
}

test_pi_detected_by_env_dir() {
  local home="$TEMP_DIR/pi-env-home"
  local stub_dir="$TEMP_DIR/pi-env-stub"
  local log="$TEMP_DIR/pi-env.log"
  local pi_dir="$TEMP_DIR/pi-env-dir"
  mkdir -p "$home" "$pi_dir"
  make_pi_stubs "$stub_dir" "$log"
  PI_CODING_AGENT_DIR="$pi_dir" PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --no-cli --yes >/dev/null
  assert_contains "varde-toz install pi --dir $pi_dir" "$log"
  assert_contains "varde-code hooks remove --agent pi --dir $pi_dir/extensions" "$log"
  assert_contains "varde-workflow hook install --harness pi" "$log"
  [ -f "$pi_dir/agents/varde-executor.md" ] || fail "pi agents missed PI_CODING_AGENT_DIR"
}

test_pi_dry_run() {
  local home="$TEMP_DIR/pi-dry-home"
  local stub_dir="$TEMP_DIR/pi-dry-stub"
  local log="$TEMP_DIR/pi-dry.log"
  local output="$TEMP_DIR/pi-dry.out"
  mkdir -p "$home"
  make_pi_stubs "$stub_dir" "$log"
  PATH="$stub_dir:$SAFE_PATH" HOME="$home" "$ROOT_DIR/varde" sync --dry-run --agents pi >"$output"
  assert_contains "would run: varde-toz install pi" "$output"
  assert_contains "would run: varde-code hooks remove --agent pi" "$output"
  assert_contains "would run: varde-workflow hook install --harness pi" "$output"
  [ ! -s "$log" ] || fail "dry run executed pi commands"
  [ ! -e "$home/.pi" ] || fail "dry run wrote pi files"
}

test_pi_agent_format_accepted() {
  local home="$TEMP_DIR/pi-format-home"
  local target="$TEMP_DIR/pi-format-agents"
  mkdir -p "$home"
  HOME="$home" "$ROOT_DIR/varde" sync --no-cli --agents-dir "$target" --agent-format pi >/dev/null
  [ -f "$target/varde-executor.md" ] || fail "--agent-format pi did not install agents"
}

test_dry_run
test_skill_dry_run_parity
test_no_tty
test_no_tty_without_detected_harnesses
test_repeated_install_and_foreign_file
test_list_agents
test_listed_agents_are_valid
test_install_preserves_harness_startup_config
test_unmarked_skill_dir_preserved_by_yes
test_custom_skills_dir_installs_there
test_shared_skill_links
test_retired_skill_links_removed
test_custom_agents_dir_requires_format
test_custom_agents_dir_installs_format
test_only_custom_targets_skip_detected_harnesses
test_toz_install_when_present
test_toz_dry_run_when_present
test_toz_absent
test_learn_cli_dry_run_prints_install_line
test_no_cli_warns_varde_learn_missing
test_toz_store_set_when_unset
test_toz_store_uses_xdg_config_home
test_toz_store_preserves_legacy_default
test_toz_store_uses_canonical_alias_target
test_toz_store_not_set_when_present
test_toz_store_dry_run
test_toz_store_set_failure_prints_hint
test_toz_store_paths_read_failure_skips
test_toz_store_paths_bad_json_skips
test_session_hook_remove_then_install
test_session_hook_dry_run
test_session_hook_reports_skipped_modified
test_instructions_install_for_configured_targets
test_instructions_warn_without_targets_under_yes
test_instructions_dry_run_prints_install_command
test_prompted_home_targets_expand_tilde
test_pi_sync_order_and_no_skills_link
test_pi_detected_by_env_dir
test_pi_dry_run
test_pi_agent_format_accepted

echo "varde sync tests passed"
