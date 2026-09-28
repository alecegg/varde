#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-sync-cli.XXXXXX")"
TEST_ROOT="$(cd "$TEST_ROOT" && pwd -P)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
SYSTEM_PATH=/usr/bin:/bin

# Missing Cargo must fail before any installer or toz write.
mkdir -p "$TEST_ROOT/no-cargo"
if HOME="$TEST_ROOT/no-cargo" PATH="$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes >"$TEST_ROOT/no-cargo.out" 2>&1; then
  fail "sync succeeded without cargo"
fi
grep -Fq 'https://rustup.rs' "$TEST_ROOT/no-cargo.out" || fail "missing rustup hint"
grep -Fq -- '--no-cli' "$TEST_ROOT/no-cargo.out" || fail "missing opt-out hint"
[ -z "$(find "$TEST_ROOT/no-cargo" -mindepth 1 -print -quit)" ] ||
  fail "sync wrote to HOME before detecting missing cargo"

mkdir -p "$TEST_ROOT/no-cli"
HOME="$TEST_ROOT/no-cli" PATH="$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes --no-cli >"$TEST_ROOT/no-cli.out" 2>&1
[ -f "$TEST_ROOT/no-cli/.agents/skills/varde-change/SKILL.md" ] ||
  fail "--no-cli did not wire skills"
for cli in varde-code varde-workflow varde-learn; do
  grep -Fq "$cli not found; install it with: cargo install --path" "$TEST_ROOT/no-cli.out" ||
    fail "--no-cli did not explain how to install $cli"
done

mkdir -p "$TEST_ROOT/dry"
HOME="$TEST_ROOT/dry" PATH="$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --dry-run >"$TEST_ROOT/dry.out" 2>&1
grep -Fq "would run: cargo install --path $ROOT_DIR/clis/code/crates/varde-code --locked --force --target-dir $ROOT_DIR/clis/code/target" "$TEST_ROOT/dry.out" ||
  fail "dry run omitted varde-code command"
grep -Fq "would run: cargo install --path $ROOT_DIR/clis/workflow/varde-workflow --locked --force --target-dir $ROOT_DIR/clis/workflow/target" "$TEST_ROOT/dry.out" ||
  fail "dry run omitted varde-workflow command"
grep -Fq "would run: cargo install --path $ROOT_DIR/clis/toz/crates/toz --locked --force --target-dir $ROOT_DIR/clis/toz/target" "$TEST_ROOT/dry.out" ||
  fail "dry run omitted toz command"
grep -Fq "would run: cargo install --path $ROOT_DIR/clis/learn/crates/varde-learn --locked --force --target-dir $ROOT_DIR/clis/learn/target" "$TEST_ROOT/dry.out" ||
  fail "dry run omitted varde-learn command"
[ -z "$(find "$TEST_ROOT/dry" -mindepth 1 -print -quit)" ] || fail "dry run wrote to HOME"

# Cargo's installed binary must be the one selected by PATH.
mkdir -p "$TEST_ROOT/shadow/bin" "$TEST_ROOT/shadow/home"
cat > "$TEST_ROOT/shadow/bin/cargo" <<'EOF'
#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    */varde-code) cli=varde-code ;;
    */varde-workflow) cli=varde-workflow ;;
    */varde-learn) cli=varde-learn ;;
    */toz) cli=varde-toz ;;
  esac
done
mkdir -p "${CARGO_INSTALL_ROOT:-${CARGO_HOME:-$HOME/.cargo}}/bin"
printf '#!/bin/sh\nexit 0\n' > "${CARGO_INSTALL_ROOT:-${CARGO_HOME:-$HOME/.cargo}}/bin/$cli"
chmod +x "${CARGO_INSTALL_ROOT:-${CARGO_HOME:-$HOME/.cargo}}/bin/$cli"
EOF
printf '#!/bin/sh\nexit 0\n' > "$TEST_ROOT/shadow/bin/varde-code"
chmod +x "$TEST_ROOT/shadow/bin/cargo" "$TEST_ROOT/shadow/bin/varde-code"
if HOME="$TEST_ROOT/shadow/home" PATH="$TEST_ROOT/shadow/bin:$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes >"$TEST_ROOT/shadow.out" 2>&1; then
  fail "sync accepted a shadowing varde-code"
fi
grep -Fq "$TEST_ROOT/shadow/home/.cargo/bin/varde-code" "$TEST_ROOT/shadow.out" ||
  fail "shadow error omitted Cargo install path"
grep -Fq "$TEST_ROOT/shadow/bin/varde-code" "$TEST_ROOT/shadow.out" ||
  fail "shadow error omitted selected path"
grep -Fq 'before other bin directories on PATH' "$TEST_ROOT/shadow.out" ||
  fail "shadow error omitted PATH remedy"

mkdir -p "$TEST_ROOT/installed/home" "$TEST_ROOT/installed/bin"
cp "$TEST_ROOT/shadow/bin/cargo" "$TEST_ROOT/installed/bin/cargo"
HOME="$TEST_ROOT/installed/home" \
  PATH="$TEST_ROOT/installed/home/.cargo/bin:$TEST_ROOT/installed/bin:$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes >"$TEST_ROOT/installed.out" 2>&1
for cli in varde-code varde-workflow varde-learn varde-toz; do
  [ -x "$TEST_ROOT/installed/home/.cargo/bin/$cli" ] || fail "sync did not install $cli"
done
[ -f "$TEST_ROOT/installed/home/.agents/skills/varde-change/SKILL.md" ] ||
  fail "sync did not wire skills after installing CLIs"

# A PATH symlink to Cargo's new binary selects the same executable.
mkdir -p "$TEST_ROOT/symlink/home" "$TEST_ROOT/symlink/bin"
cp "$TEST_ROOT/shadow/bin/cargo" "$TEST_ROOT/symlink/bin/cargo"
for cli in varde-code varde-workflow varde-learn varde-toz; do
  ln -s "$TEST_ROOT/symlink/home/.cargo/bin/$cli" "$TEST_ROOT/symlink/bin/$cli"
done
HOME="$TEST_ROOT/symlink/home" PATH="$TEST_ROOT/symlink/bin:$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes >"$TEST_ROOT/symlink.out" 2>&1 ||
  fail "sync rejected PATH symlinks to newly installed CLIs"
[ -f "$TEST_ROOT/symlink/home/.agents/skills/varde-change/SKILL.md" ] ||
  fail "sync did not wire skills with PATH symlinks"

# Cargo's install.root config takes precedence over CARGO_HOME itself.
mkdir -p "$TEST_ROOT/configured/home/.cargo" "$TEST_ROOT/configured/bin" \
  "$TEST_ROOT/configured/install/bin"
printf '[install]\nroot = "%s"\n' "$TEST_ROOT/configured/install" > \
  "$TEST_ROOT/configured/home/.cargo/config.toml"
cat > "$TEST_ROOT/configured/bin/cargo" <<'EOF'
#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    */varde-code) cli=varde-code ;;
    */varde-workflow) cli=varde-workflow ;;
    */varde-learn) cli=varde-learn ;;
    */toz) cli=varde-toz ;;
  esac
done
root=$(sed -n 's/^root = "\(.*\)"$/\1/p' "$CARGO_HOME/config.toml")
printf '#!/bin/sh\nexit 0\n' > "$root/bin/$cli"
chmod +x "$root/bin/$cli"
EOF
chmod +x "$TEST_ROOT/configured/bin/cargo"
HOME="$TEST_ROOT/configured/home" CARGO_HOME="$TEST_ROOT/configured/home/.cargo" \
  PATH="$TEST_ROOT/configured/install/bin:$TEST_ROOT/configured/bin:$SYSTEM_PATH" \
  "$ROOT_DIR/varde" sync --agents claude --yes >"$TEST_ROOT/configured.out" 2>&1 ||
  fail "sync rejected Cargo's configured install.root"
for cli in varde-code varde-workflow varde-learn varde-toz; do
  [ -x "$TEST_ROOT/configured/install/bin/$cli" ] ||
    fail "Cargo did not install $cli to configured root"
done

# With --path, Cargo starts config discovery at each package directory.
fixture_repo="$TEST_ROOT/package-config/repo"
fixture_home="$TEST_ROOT/package-config/home"
mkdir -p "$fixture_repo/clis/code/crates/varde-code/.cargo" \
  "$fixture_repo/clis/workflow/varde-workflow/.cargo" \
  "$fixture_repo/clis/learn/crates/varde-learn/.cargo" \
  "$fixture_repo/clis/toz/crates/toz/.cargo" "$fixture_home/.cargo" \
  "$TEST_ROOT/package-config/bin"
cp "$ROOT_DIR/varde" "$fixture_repo/varde"
ln -s "$ROOT_DIR/skills" "$fixture_repo/skills"
ln -s "$ROOT_DIR/agents" "$fixture_repo/agents"
printf '[install]\nroot = "/wrong-root"\n' > "$fixture_home/.cargo/config.toml"
for package_dir in "$fixture_repo/clis/code/crates/varde-code" \
  "$fixture_repo/clis/workflow/varde-workflow" \
  "$fixture_repo/clis/learn/crates/varde-learn" "$fixture_repo/clis/toz/crates/toz"; do
  printf '[install]\nroot = "install"\n' > "$package_dir/.cargo/config.toml"
  mkdir -p "$package_dir/install/bin"
done
cat > "$TEST_ROOT/package-config/bin/cargo" <<'EOF'
#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    */varde-code) package_dir=$arg; cli=varde-code ;;
    */varde-workflow) package_dir=$arg; cli=varde-workflow ;;
    */varde-learn) package_dir=$arg; cli=varde-learn ;;
    */toz) package_dir=$arg; cli=varde-toz ;;
  esac
done
printf '#!/bin/sh\nexit 0\n' > "$package_dir/install/bin/$cli"
chmod +x "$package_dir/install/bin/$cli"
EOF
chmod +x "$TEST_ROOT/package-config/bin/cargo"
HOME="$fixture_home" CARGO_HOME="$fixture_home/.cargo" \
PATH="$fixture_repo/clis/code/crates/varde-code/install/bin:\
$fixture_repo/clis/workflow/varde-workflow/install/bin:\
$fixture_repo/clis/learn/crates/varde-learn/install/bin:\
$fixture_repo/clis/toz/crates/toz/install/bin:\
$TEST_ROOT/package-config/bin:$SYSTEM_PATH" \
  "$fixture_repo/varde" sync --agents claude --yes >"$TEST_ROOT/package-config.out" 2>&1 ||
  fail "sync ignored package config or misresolved relative install.root"
for cli in varde-code varde-workflow varde-learn varde-toz; do
  case "$cli" in
    varde-code) package_dir="$fixture_repo/clis/code/crates/varde-code" ;;
    varde-workflow) package_dir="$fixture_repo/clis/workflow/varde-workflow" ;;
    varde-learn) package_dir="$fixture_repo/clis/learn/crates/varde-learn" ;;
    varde-toz) package_dir="$fixture_repo/clis/toz/crates/toz" ;;
  esac
  [ -x "$package_dir/install/bin/$cli" ] || fail "package config did not install $cli"
done

# Exercise the current workflow CLI against a valid config in both modes.
cargo build --manifest-path "$ROOT_DIR/clis/workflow/Cargo.toml" -p varde-workflow --locked -q
REAL_WORKFLOW="$ROOT_DIR/clis/workflow/target/debug/varde-workflow"
for mode in default no-cli; do
  mode_root="$TEST_ROOT/toz-$mode"
  mkdir -p "$mode_root/home" "$mode_root/bin" "$mode_root/config"
  printf '[default]\ntoz = "/existing/toz"\n' > "$mode_root/config/paths.toml"
  cp "$mode_root/config/paths.toml" "$mode_root/paths.before"
  cat > "$mode_root/bin/toz" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$TEST_LOG"
EOF
  cat > "$mode_root/bin/workflow-real" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$WORKFLOW_LOG"
exec "$REAL_WORKFLOW" "$@"
EOF
  chmod +x "$mode_root/bin/toz" "$mode_root/bin/workflow-real"
  if [ "$mode" = default ]; then
    cat > "$mode_root/bin/cargo" <<'EOF'
#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    */varde-code) cli=varde-code ;;
    */varde-workflow) cli=varde-workflow ;;
    */varde-learn) cli=varde-learn ;;
    */toz) cli=varde-toz ;;
  esac
done
bin="$HOME/.cargo/bin"
mkdir -p "$bin"
if [ "$cli" = varde-workflow ]; then
  cp "$WORKFLOW_LAUNCHER" "$bin/$cli"
elif [ "$cli" = varde-toz ]; then
  cp "$TOZ_LAUNCHER" "$bin/$cli"
else
  printf '#!/bin/sh\nexit 0\n' > "$bin/$cli"
fi
chmod +x "$bin/$cli"
EOF
    chmod +x "$mode_root/bin/cargo"
    mode_path="$mode_root/home/.cargo/bin:$mode_root/bin:$SYSTEM_PATH"
    cli_flag=""
  else
    ln -s "$mode_root/bin/workflow-real" "$mode_root/bin/varde-workflow"
    mode_path="$mode_root/bin:$SYSTEM_PATH"
    cli_flag=--no-cli
  fi
  before=$(VARDE_CONFIG_DIR="$mode_root/config" "$REAL_WORKFLOW" paths --json | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["toz"])')
  [ "$before" = /existing/toz ] || fail "invalid $mode toz fixture"
  HOME="$mode_root/home" VARDE_CONFIG_DIR="$mode_root/config" \
    PATH="$mode_path" REAL_WORKFLOW="$REAL_WORKFLOW" \
    WORKFLOW_LAUNCHER="$mode_root/bin/workflow-real" TOZ_LAUNCHER="$mode_root/bin/toz" \
    WORKFLOW_LOG="$mode_root/workflow.log" \
    TEST_LOG="$mode_root/toz.log" \
    "$ROOT_DIR/varde" sync --agents claude --yes $cli_flag >"$mode_root/sync.out" 2>&1
  after=$(VARDE_CONFIG_DIR="$mode_root/config" "$REAL_WORKFLOW" paths --json | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["toz"])')
  [ "$after" = /existing/toz ] || fail "sync changed $mode resolved toz path"
  cmp -s "$mode_root/paths.before" "$mode_root/config/paths.toml" ||
    fail "sync rewrote $mode toz config"
  grep -Fxq 'install claude-code' "$mode_root/toz.log" ||
    fail "sync skipped $mode toz install"
  grep -Fxq 'paths --json' "$mode_root/workflow.log" ||
    fail "sync did not read $mode paths through the real workflow CLI"
  if grep -Fq 'paths set' "$mode_root/workflow.log"; then
    fail "sync tried to replace the existing $mode toz path"
  fi
done

echo 'sync CLI installation checks passed'
