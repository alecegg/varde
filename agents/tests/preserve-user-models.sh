#!/usr/bin/env bash
# install.sh keeps user-changed model settings and refreshes unchanged ones.
set -euo pipefail
# Pin the OpenCode adapter generation so results never depend on the host.
export VARDE_AGENTS_OPENCODE_VERSION="${VARDE_AGENTS_OPENCODE_VERSION:-1.4.0}"
OPENCODE_VARIANT=opencode.md
[ "${VARDE_AGENTS_OPENCODE_VERSION%%.*}" -lt 2 ] || OPENCODE_VARIANT=opencode-v2.md

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-preserve-models.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

AGENT=varde-planner
CASE=0

# line_of FILE PREFIX: first line starting with PREFIX.
line_of() {
  awk -v p="$2" 'index($0, p) == 1 { print; exit }' "$1"
}

# replace_line FILE PREFIX NEW: replace the first line starting with PREFIX.
replace_line() {
  awk -v p="$2" -v n="$3" 'index($0, p) == 1 && !done { print n; done = 1; next } { print }' \
    "$1" >"$1.tmp"
  mv "$1.tmp" "$1"
}

# remove_line FILE PREFIX
remove_line() {
  awk -v p="$2" 'index($0, p) == 1 && !done { done = 1; next } { print }' "$1" >"$1.tmp"
  mv "$1.tmp" "$1"
}

# install ARGS...: run the installer under test with an isolated HOME.
install() {
  HOME="$HOME_DIR" bash "$INSTALLER" -t "$H" -d "$TGT" "$@"
}

# install_tty ARGS...: same, but with a pseudo-terminal on stdin answering y.
install_tty() {
  HOME="$HOME_DIR" python3 - "$INSTALLER" -t "$H" -d "$TGT" "$@" <<'PY'
import os, pty, subprocess, sys
try:
    master, slave = pty.openpty()
except OSError:
    sys.exit(77)  # no pseudo-terminal available (for example, sandboxed)
os.write(master, b"y\n")
sys.exit(subprocess.run(["bash"] + sys.argv[1:], stdin=slave).returncode)
PY
}

PTY_SKIPPED=0

# new_case: fresh TGT/HOME_DIR/installer for the current harness.
new_case() {
  CASE=$((CASE + 1))
  CASE_DIR="$TEST_ROOT/$H-$CASE"
  TGT="$CASE_DIR/target"
  HOME_DIR="$CASE_DIR/home"
  INSTALLER="$AGENTS_DIR/install.sh"
  mkdir -p "$TGT" "$HOME_DIR"
  DEST="$TGT/$AGENT.$EXT"
}

# shipped_copy: private copy of agents/ whose variant has a different model.
shipped_copy() {
  local copy="$CASE_DIR/agents-old"
  mkdir -p "$copy"
  cp -R "$AGENTS_DIR/." "$copy/"
  replace_line "$copy/$AGENT/$VARIANT" "$MODEL_PREFIX" "$MODEL_PREFIX$1"
  [ -z "${2:-}" ] || replace_line "$copy/$AGENT/$VARIANT" "$EFFORT_PREFIX" "$EFFORT_PREFIX$2"
  OLD_INSTALLER="$copy/install.sh"
}

managed_marker() {
  case "$EXT" in
    md) echo '<!-- varde-managed-agent -->' ;;
    toml) echo '# varde-managed-agent' ;;
  esac
}

# make_legacy FILE MODEL [EFFORT]: a managed file with no recorded defaults.
make_legacy() {
  cp "$AGENTS_DIR/$AGENT/$VARIANT" "$1"
  replace_line "$1" "$MODEL_PREFIX" "$MODEL_PREFIX$2"
  [ -z "${3:-}" ] || replace_line "$1" "$EFFORT_PREFIX" "$EFFORT_PREFIX$3"
  printf '\n%s\n' "$(managed_marker)" >>"$1"
}

# strip_models FILE: drop model lines, recorded defaults, the marker, and blank
# trailing lines so only unrelated content is compared.
strip_models() {
  awk '/^model(_reasoning_effort)?(:| =) / || /varde-default:/ || /varde-managed-agent/ { next }
       /^$/ { blank++; next } { while (blank > 0) { print ""; blank-- } print }' "$1"
}

snapshot() {
  (cd "$1" && find . | sort | while IFS= read -r f; do
    if [ -L "$f" ]; then echo "L $f"; elif [ -f "$f" ]; then echo "F $f $(cksum <"$f")"; else echo "D $f"; fi
  done)
}

assert_line() { # FILE PREFIX EXPECTED
  [ "$(line_of "$1" "$2")" = "$3" ] || fail "$H: $1: expected '$3', got '$(line_of "$1" "$2")'"
}

assert_no_line() {
  [ -z "$(line_of "$1" "$2")" ] || fail "$H: $1: unexpected '$(line_of "$1" "$2")'"
}

assert_current_models() {
  assert_line "$1" "$MODEL_PREFIX" "$SHIPPED_MODEL"
  [ -z "$EFFORT_PREFIX" ] || assert_line "$1" "$EFFORT_PREFIX" "$SHIPPED_EFFORT"
}

run_harness() {
  H="$1"
  case "$H" in
    claude) VARIANT=claude.md; EXT=md; MODEL_PREFIX='model: '; EFFORT_PREFIX='' ;;
    codex) VARIANT=codex.toml; EXT=toml; MODEL_PREFIX='model = '; EFFORT_PREFIX='model_reasoning_effort = ' ;;
    opencode) VARIANT="$OPENCODE_VARIANT"; EXT=md; MODEL_PREFIX='model: '; EFFORT_PREFIX='' ;;
  esac
  SHIPPED_MODEL="$(line_of "$AGENTS_DIR/$AGENT/$VARIANT" "$MODEL_PREFIX")"
  SHIPPED_EFFORT=''
  [ -z "$EFFORT_PREFIX" ] || SHIPPED_EFFORT="$(line_of "$AGENTS_DIR/$AGENT/$VARIANT" "$EFFORT_PREFIX")"
  CUSTOM_MODEL="${MODEL_PREFIX}\"user-custom-model\""
  CUSTOM_EFFORT="${EFFORT_PREFIX}\"user-custom-effort\""
  local marker default_re
  marker="$(managed_marker)"
  case "$EXT" in
    md) default_re="<!-- varde-default: $SHIPPED_MODEL -->" ;;
    toml) default_re="# varde-default: $SHIPPED_MODEL" ;;
  esac

  # 1. Fresh install records defaults; marker stays an exact standalone line.
  new_case
  install -m -a "$AGENT" >/dev/null
  assert_current_models "$DEST"
  grep -Fqx "$default_re" "$DEST" || fail "$H: fresh install did not record '$default_re'"
  [ "$(grep -Fxc "$marker" "$DEST")" = 1 ] || fail "$H: marker line not exact and unique"
  grep -F 'varde-default:' "$DEST" | grep -Fq 'varde-managed-agent' && fail "$H: default line contains marker text"
  if [ "$H" = codex ]; then
    grep -Fqx "# varde-default: $SHIPPED_EFFORT" "$DEST" || fail "codex: effort default not recorded"
  fi

  # 2. Unchanged values take the new shipped value.
  new_case
  shipped_copy '"old-shipped-model"' "$([ -z "$EFFORT_PREFIX" ] || echo '"old-effort"')"
  HOME="$HOME_DIR" bash "$OLD_INSTALLER" -t "$H" -d "$TGT" -m -a "$AGENT" >/dev/null
  assert_line "$DEST" "$MODEL_PREFIX" "${MODEL_PREFIX}\"old-shipped-model\""
  install -m -a "$AGENT" >/dev/null
  assert_current_models "$DEST"

  # 3. User-changed settings survive -m, -f, and prompt-accept; others refresh.
  for mode in -m -f prompt; do
    new_case
    shipped_copy '"old-shipped-model"' "$([ -z "$EFFORT_PREFIX" ] || echo '"old-effort"')"
    HOME="$HOME_DIR" bash "$OLD_INSTALLER" -t "$H" -d "$TGT" -m -a "$AGENT" >/dev/null
    replace_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
    [ -z "$EFFORT_PREFIX" ] || replace_line "$DEST" "$EFFORT_PREFIX" "$CUSTOM_EFFORT"
    if [ "$mode" = prompt ]; then
      rc=0
      install_tty -a "$AGENT" >/dev/null 2>&1 || rc=$?
      if [ "$rc" -eq 77 ]; then
        echo "SKIP: $H prompt-accept (no pty available)"
        PTY_SKIPPED=1
        continue
      fi
      [ "$rc" -eq 0 ] || fail "$H: prompt-accept install failed ($rc)"
    else
      install "$mode" -a "$AGENT" >/dev/null
    fi
    assert_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
    [ -z "$EFFORT_PREFIX" ] || assert_line "$DEST" "$EFFORT_PREFIX" "$CUSTOM_EFFORT"
    # Only model lines (and the appended trailer) differ from the variant.
    strip_models "$AGENTS_DIR/$AGENT/$VARIANT" >"$CASE_DIR/variant.txt"
    strip_models "$DEST" >"$CASE_DIR/installed.txt"
    cmp -s "$CASE_DIR/variant.txt" "$CASE_DIR/installed.txt" ||
      fail "$H $mode: preserved file differs from variant outside model lines"
  done

  # 4. A key the user removed stays removed.
  new_case
  install -m -a "$AGENT" >/dev/null
  remove_line "$DEST" "$MODEL_PREFIX"
  [ -z "$EFFORT_PREFIX" ] || remove_line "$DEST" "$EFFORT_PREFIX"
  install -m -a "$AGENT" >/dev/null
  assert_no_line "$DEST" "$MODEL_PREFIX"
  [ -z "$EFFORT_PREFIX" ] || assert_no_line "$DEST" "$EFFORT_PREFIX"

  # 5. Legacy file (no recorded defaults): historical varde value updates,
  #    non-varde value is preserved.
  new_case
  case "$H" in
    codex) make_legacy "$DEST" '"gpt-5.6-terra"' '"high"' ;;
    claude) make_legacy "$DEST" '"sonnet"' ;;
    opencode) make_legacy "$DEST" '"deepseek/deepseek-v4-flash"' ;;
  esac
  install -m -a "$AGENT" >/dev/null
  assert_current_models "$DEST"
  if [ "$H" = claude ]; then
    new_case
    make_legacy "$TGT/varde-reviewer.md" '"haiku"'
    install -m -a varde-reviewer >/dev/null
    assert_line "$TGT/varde-reviewer.md" "$MODEL_PREFIX" "$(line_of "$AGENTS_DIR/varde-reviewer/$VARIANT" "$MODEL_PREFIX")"
    # varde never shipped sonnet for the reviewer, so it is a user choice.
    new_case
    make_legacy "$TGT/varde-reviewer.md" '"sonnet"'
    install -m -a varde-reviewer >/dev/null
    assert_line "$TGT/varde-reviewer.md" "$MODEL_PREFIX" "${MODEL_PREFIX}\"sonnet\""
    # The explorer shipped sonnet before haiku, so legacy sonnet updates.
    new_case
    make_legacy "$TGT/varde-explorer.md" '"sonnet"'
    install -m -a varde-explorer >/dev/null
    assert_line "$TGT/varde-explorer.md" "$MODEL_PREFIX" 'model: "haiku"'
    new_case
    make_legacy "$TGT/varde-explorer.md" '"opus"'
    install -m -a varde-explorer >/dev/null
    assert_line "$TGT/varde-explorer.md" "$MODEL_PREFIX" 'model: "opus"'
  fi
  new_case
  make_legacy "$DEST" '"user-custom-model"' "$([ -z "$EFFORT_PREFIX" ] || echo '"user-custom-effort"')"
  install -m -a "$AGENT" >/dev/null
  assert_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
  [ -z "$EFFORT_PREFIX" ] || assert_line "$DEST" "$EFFORT_PREFIX" "$CUSTOM_EFFORT"

  # 6. Carry-over from the v1.4 plan.<ext> name; unowned plan file ignored.
  for mode in -m -f; do
    new_case
    make_legacy "$TGT/plan.$EXT" '"user-custom-model"'
    install "$mode" -a "$AGENT" >/dev/null
    assert_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
    [ ! -e "$TGT/plan.$EXT" ] || fail "$H: renamed file not retired"
  done
  new_case
  cp "$AGENTS_DIR/$AGENT/$VARIANT" "$TGT/plan.$EXT"
  replace_line "$TGT/plan.$EXT" "$MODEL_PREFIX" "$CUSTOM_MODEL"
  install -m -a "$AGENT" >/dev/null
  assert_current_models "$DEST"
  # Executor carries over from build.<ext>.
  new_case
  make_legacy "$TGT/build.$EXT" '"user-custom-model"'
  install -m -a varde-executor >/dev/null
  assert_line "$TGT/varde-executor.$EXT" "$MODEL_PREFIX" "$CUSTOM_MODEL"

  # 7. Opencode V1 agent dir carry-over (default target, isolated HOME).
  if [ "$H" = opencode ]; then
    new_case
    mkdir -p "$HOME_DIR/.config/opencode/agent"
    make_legacy "$HOME_DIR/.config/opencode/agent/plan.md" '"user-custom-model"'
    HOME="$HOME_DIR" bash "$INSTALLER" -t opencode -m -a "$AGENT" >/dev/null
    assert_line "$HOME_DIR/.config/opencode/agents/$AGENT.md" "$MODEL_PREFIX" "$CUSTOM_MODEL"
    [ ! -e "$HOME_DIR/.config/opencode/agent/plan.md" ] || fail "opencode: V1 file not retired"
  fi

  # 8. Unowned files and symlinks are untouched or never read.
  new_case
  cp "$AGENTS_DIR/$AGENT/$VARIANT" "$DEST"
  replace_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
  before="$(cksum <"$DEST")"
  install -m -a "$AGENT" >/dev/null
  [ "$(cksum <"$DEST")" = "$before" ] || fail "$H: -m changed unowned file"
  install -f -a "$AGENT" >/dev/null
  assert_current_models "$DEST"
  new_case
  make_legacy "$CASE_DIR/elsewhere" '"user-custom-model"'
  ln -s "$CASE_DIR/elsewhere" "$DEST"
  before="$(cksum <"$CASE_DIR/elsewhere")"
  install -m -a "$AGENT" >/dev/null
  [ -L "$DEST" ] || fail "$H: -m replaced symlink"
  install -f -a "$AGENT" >/dev/null
  [ ! -L "$DEST" ] || fail "$H: -f kept symlink"
  assert_current_models "$DEST"
  [ "$(cksum <"$CASE_DIR/elsewhere")" = "$before" ] || fail "$H: symlink target modified"

  # 9. Dry run changes nothing and leaves no temp files.
  new_case
  install -m -a "$AGENT" >/dev/null
  replace_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
  before="$(snapshot "$TGT")"
  out="$(install -m -n -a "$AGENT")"
  [ "$(snapshot "$TGT")" = "$before" ] || fail "$H: dry run changed TARGET"
  printf '%s\n' "$out" | grep -Fq "Would preserve user model setting model in $DEST" ||
    fail "$H: dry run did not report preservation"
  [ -z "$(find "$TGT" -name '.varde-agent*')" ] || fail "$H: dry run left temp files"
  real="$(install -m -a "$AGENT")"
  printf '%s\n' "$real" | grep -Fq "Preserved user model setting model in $DEST" ||
    fail "$H: real run did not report preservation"

  # 10. Helper failure leaves dest byte-identical and fails the install.
  new_case
  install -m -a "$AGENT" >/dev/null
  replace_line "$DEST" "$MODEL_PREFIX" "$CUSTOM_MODEL"
  broken="$CASE_DIR/agents-broken"
  mkdir -p "$broken"
  cp -R "$AGENTS_DIR/." "$broken/"
  printf 'import sys\nsys.exit(3)\n' >"$broken/preserve-models.py"
  before="$(snapshot "$TGT")"
  if HOME="$HOME_DIR" bash "$broken/install.sh" -t "$H" -d "$TGT" -m -a "$AGENT" >/dev/null 2>&1; then
    fail "$H: helper failure did not fail the install"
  fi
  [ "$(snapshot "$TGT")" = "$before" ] || fail "$H: helper failure changed TARGET"
  echo "ok: $H"
}

for harness in claude codex opencode; do
  run_harness "$harness"
done
# Pi inherits the session model: the shipped file has no model line.
PIN='"deepseek/deepseek-v4-flash"'

# make_pi_old FILE MODEL [record]: a managed pre-change Pi file with a model line.
make_pi_old() {
  awk -v m="model: $2" '{ print } /^description:/ { print m }' "$AGENTS_DIR/$AGENT/pi.md" >"$1"
  printf '\n<!-- varde-managed-agent -->\n' >>"$1"
  [ "${3:-}" != record ] || printf '<!-- varde-default: model: %s -->\n' "$PIN" >>"$1"
}

run_pi() {
  H=pi; VARIANT=pi.md; EXT=md; MODEL_PREFIX='model: '
  assert_no_line "$AGENTS_DIR/$AGENT/pi.md" "$MODEL_PREFIX"

  # 1. Fresh install ships no model line and records no model default.
  new_case
  install -m -a "$AGENT" >/dev/null
  assert_no_line "$DEST" "$MODEL_PREFIX"
  ! grep -Fq 'varde-default: model' "$DEST" || fail "pi: fresh install recorded a model default"

  # 2. The old pin is dropped, with or without a recorded default.
  for kind in record legacy; do
    new_case
    if [ "$kind" = record ]; then make_pi_old "$DEST" "$PIN" record; else make_pi_old "$DEST" "$PIN"; fi
    install -m -a "$AGENT" >/dev/null
    assert_no_line "$DEST" "$MODEL_PREFIX"
  done

  # 3. A user-chosen model is inserted after description, with no new record.
  for kind in record legacy; do
    new_case
    if [ "$kind" = record ]; then make_pi_old "$DEST" '"user-custom-model"' record; else make_pi_old "$DEST" '"user-custom-model"'; fi
    install -m -a "$AGENT" >/dev/null
    assert_line "$DEST" "$MODEL_PREFIX" "$MODEL_PREFIX\"user-custom-model\""
    [ "$(grep -n '^model:' "$DEST" | cut -d: -f1)" = "$(($(grep -n '^description:' "$DEST" | cut -d: -f1) + 1))" ] ||
      fail "pi: model not inserted after description"
    ! grep -Fq 'varde-default: model' "$DEST" || fail "pi: inserted model got a recorded default"
    install -f -a "$AGENT" >/dev/null
    assert_line "$DEST" "$MODEL_PREFIX" "$MODEL_PREFIX\"user-custom-model\""
  done

  # 4. Without a description line the model goes before the closing ---.
  new_case
  printf -- '---\ntools: read\n---\nbody\n' >"$CASE_DIR/staged.md"
  printf -- '---\ntools: read\nmodel: "mine"\n---\nbody\n' >"$CASE_DIR/installed.md"
  python3 "$AGENTS_DIR/preserve-models.py" --harness pi --agent "$AGENT" \
    --staged "$CASE_DIR/staged.md" --installed "$CASE_DIR/installed.md" >/dev/null
  cmp -s "$CASE_DIR/staged.md" "$CASE_DIR/installed.md" || fail "pi: model not inserted before closing ---"
  echo "ok: pi"
}
run_pi

if [ "$PTY_SKIPPED" -eq 1 ]; then
  echo "Preserve user models: ok, prompt-accept NOT exercised (no pty)"
else
  echo "Preserve user models: ok (prompt-accept exercised through a python pty)"
fi
