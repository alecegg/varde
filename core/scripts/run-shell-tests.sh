#!/usr/bin/env bash
# Run every shell test under <root>/*/tests and report one PASS/FAIL/SKIP line
# per script. Exits nonzero when a test fails, times out, or the protected Varde
# config changed during the run.
#
# Usage:
#   core/scripts/run-shell-tests.sh [--root DIR] [--timeout SECONDS]
#       [--tier fast|all] [--tiers FILE] [--list] [--self-test]
#
#   --root DIR       tree to scan (default: this repository)
#   --timeout SECS   per-script limit, a non-negative integer; 0 disables
#                    (default: $SHELL_TEST_TIMEOUT or 900)
#   --tier fast|all  fast runs the fast tier only, all runs every script
#                    (default: all)
#   --tiers FILE     tier list (default: <root>/core/scripts/shell-test-tiers.txt);
#                    this repository's own list, and any file named here, must
#                    exist, while another --root tree may omit one (then every
#                    script runs in every tier, listed as untiered)
#   --list           print RUN/SKIP and the tier of every script without running it
#   --self-test      exercise discovery, skip classification, tier validation, env
#                    isolation, the timeout path, the protected-config guard, and
#                    the checkout varde wrapper on scratch trees, then exit
#
# Every run prints the seconds each script took.
#
# Tiers: core/scripts/shell-test-tiers.txt lists every run script with its tier
# (fast or slow) and measured seconds. just test runs --tier fast, just test-all
# and CI run --tier all. A script missing from that file, listed twice, or listed
# but no longer discovered fails the run before any script starts, so a new test
# must be tiered. A missing tier file is an error too, unless the root is some
# other tree: this repository's own list, and any file named by --tiers, is
# required.
#
# Every discovered script is either run or listed as SKIP with a reason. A newly
# added .sh is run by default, so a test is never silently ignored.
#
# Discovery skips hidden directories (so .varde, .git, .venv and other nested
# worktrees or vendored trees are not scanned) and any directory that is the
# root of a nested git repository or worktree.
#
# Isolation: each script runs with its own HOME, XDG_CONFIG_HOME,
# VARDE_CONFIG_DIR, XDG_DATA_HOME, and TMPDIR under a private sandbox. The
# machine config named by SHELL_TEST_PROTECTED_CONFIG (md5
# 4e8e86f81be56fb9c6f7830c0e73a0d9, mtime 1792216228) is fingerprinted before
# and after; a change fails the run.
#
# PATH: each script gets a varde wrapper first on PATH that execs the scanned
# checkout's working tree (`uv run --project <root>/app varde`), so a script
# that resolves varde from PATH does not fall back to a stale global install.
# The runner prints the command it chose.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$SELF_DIR/$(basename "${BASH_SOURCE[0]}")"
source "$SELF_DIR/test-env.sh"
DEFAULT_TIMEOUT="${SHELL_TEST_TIMEOUT:-900}"
PROTECTED_CONFIG="${SHELL_TEST_PROTECTED_CONFIG:-/Users/alec/.config/varde/config.toml}"

# HOME is reset per script; keep the shared uv cache captured by test-env.sh.

# Assigned by run() and run_case(); global so the EXIT trap works after return.
SANDBOX_ROOT=""
SELF_TEST_SCRATCH=""
RUN_TIER="all"
TIERS_FILE=""
TIERS_INDEX=""
CHILD_OUT=""
CASE_INDEX=0
CASE_TIMEOUT=0
RUN_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0
CHILD_STATUS=0

cleanup() {
  [ -n "$SANDBOX_ROOT" ] && rm -rf "$SANDBOX_ROOT"
  [ -n "$SELF_TEST_SCRATCH" ] && rm -rf "$SELF_TEST_SCRATCH"
  [ -n "$TIERS_INDEX" ] && rm -f "$TIERS_INDEX" "$TIERS_INDEX".*
  return 0
}
trap cleanup EXIT

usage() {
  cat <<'EOS'
Run every shell test under <root>/*/tests and report one PASS/FAIL/SKIP line
per script. Exits nonzero when a test fails, times out, or the protected Varde
config changed during the run.

Usage:
  core/scripts/run-shell-tests.sh [--root DIR] [--timeout SECONDS]
      [--tier fast|all] [--tiers FILE] [--list] [--self-test]

  --root DIR       tree to scan (default: this repository)
  --timeout SECS   per-script limit, a non-negative integer; 0 disables
                   (default: $SHELL_TEST_TIMEOUT or 900)
  --tier fast|all  fast runs the fast tier only, all runs every script
                   (default: all)
  --tiers FILE     tier list (default: <root>/core/scripts/shell-test-tiers.txt);
                   this repository's own list, and any file named here, must
                   exist, while another --root tree may omit one (then every
                   script runs in every tier, listed as untiered)
  --list           print RUN/SKIP and the tier of every script without running it
  --self-test      exercise discovery, skip classification, tier validation, env
                   isolation, the timeout path, the protected-config guard, and
                   the checkout varde wrapper on scratch trees, then exit
EOS
}

skip_reason() {
  case "$1" in
    dev/*|code/bench/*|runner/bench/*) printf 'owned by qs-quality-pass' ;;
    */tests/lib/*) printf 'sourced test helper' ;;
    */tests/agents/*) printf 'run by just test-agents' ;;
    workflow/tests/storage-fallbacks.sh) printf 'sourced helper; run by storage-fallbacks-test.sh and check-refs.sh' ;;
    app/tests/install-shared-files.sh) printf 'run by app pytest test_shell_checks.py' ;;
    *) return 1 ;;
  esac
}

# Directories below <root> that hold a .git entry: nested clones and linked
# worktrees. The scanned root's own .git is not a nested repository.
nested_repo_roots() {
  local root="$1" entry
  find "$root" -mindepth 1 \
    -name .git -prune -print -o \
    \( -name '.*' -o -name node_modules -o -name .tox \) -prune |
    while IFS= read -r entry; do
      entry="${entry%/.git}"
      [ "$entry" = "$root" ] || printf '%s\n' "$entry"
    done
}

# Escape the characters find reads as glob syntax in a -path pattern, so a
# nested repository whose directory name holds them is pruned exactly rather
# than as a pattern.
escape_find_glob() {
  printf '%s' "$1" | sed 's/[][*?\\]/\\&/g'
}

# Every .sh below a `tests` directory, excluding hidden directories (.varde,
# .git, .venv, caches), vendored trees, and the roots of nested git
# repositories or worktrees. Those roots become prune arguments: asking find to
# test `<dir>/.git` itself would spawn one process per directory.
discover() {
  local root="$1" dir nested=()
  while IFS= read -r dir; do
    [ -n "$dir" ] || continue
    nested+=(-path "$(escape_find_glob "$dir")" -prune -o)
  done < <(nested_repo_roots "$root")

  # ${nested[@]+...} keeps bash 3.2 with `set -u` from rejecting an empty array.
  find "$root" -mindepth 1 \
    \( -name '.*' -o -name node_modules -o -name .tox \) -prune -o \
    ${nested[@]+"${nested[@]}"} \
    -type f -name '*.sh' -path '*/tests/*' -print |
    LC_ALL=C sort
}

now_seconds() {
  date +%s
}

tiers_error() {
  printf 'tiers: %s\n' "$1" >&2
  exit 2
}

# tier_of <relative path>: the tier the tier file gives a script, or "untiered".
tier_of() {
  local tier=""
  if [ -n "$TIERS_INDEX" ]; then
    tier="$(awk -F'\t' -v path="$1" '$1 == path { print $2; exit }' "$TIERS_INDEX")"
  fi
  printf '%s' "${tier:-untiered}"
}

# tier_skips <relative path>: true when --tier fast excludes a script. Untiered
# scripts (no tier file) run in every tier, so --root on another tree still runs
# everything.
tier_skips() {
  [ "$RUN_TIER" = fast ] && [ "$(tier_of "$1")" = slow ]
}

# load_tiers <file>: read the tier file into TIERS_INDEX (path<TAB>tier<TAB>seconds).
load_tiers() {
  local file="$1" line lineno=0 path tier seconds extra
  TIERS_INDEX="$(mktemp "${TMPDIR:-/tmp}/shell-tiers.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    lineno=$((lineno + 1))
    case "$line" in ''|'#'*) continue ;; esac
    read -r path tier seconds extra <<<"$line"
    case "$tier" in
      fast|slow) ;;
      *) tiers_error "$file:$lineno: tier must be fast or slow: $line" ;;
    esac
    case "$seconds" in
      ''|*[!0-9]*) tiers_error "$file:$lineno: seconds must be a non-negative integer: $line" ;;
    esac
    [ -z "${extra:-}" ] || tiers_error "$file:$lineno: want '<path> <fast|slow> <seconds>': $line"
    printf '%s\t%s\t%s\n' "$path" "$tier" "$seconds" >>"$TIERS_INDEX"
  done <"$file"
}

# validate_tiers <root>: the tier file must name every script the run would run,
# exactly once, and nothing else.
validate_tiers() {
  local root="$1" expected="$TIERS_INDEX.expected" listed="$TIERS_INDEX.listed" path
  run_list "$root" | LC_ALL=C sort >"$expected"
  cut -f1 "$TIERS_INDEX" | LC_ALL=C sort >"$listed"
  while IFS= read -r path; do
    tiers_error "$TIERS_FILE: duplicate entry for $path"
  done < <(uniq -d "$listed")
  while IFS= read -r path; do
    tiers_error "$TIERS_FILE: no entry for $path; add '$path <fast|slow> <seconds>'"
  done < <(LC_ALL=C comm -13 "$listed" "$expected")
  while IFS= read -r path; do
    tiers_error "$TIERS_FILE: entry for $path is not a script this run would run"
  done < <(LC_ALL=C comm -23 "$listed" "$expected")
}

# "md5 mtime", or "absent" when the file is not on this machine.
fingerprint() {
  local path="$1" digest mtime
  if [ ! -f "$path" ]; then
    printf 'absent'
    return 0
  fi
  digest="$(md5 -q "$path" 2>/dev/null || md5sum "$path" | cut -d' ' -f1)"
  mtime="$(stat -f '%m' "$path" 2>/dev/null || stat -c '%Y' "$path")"
  printf '%s %s' "$digest" "$mtime"
}

# Run "$@" under a wall-clock limit, then kill its whole process group so a hung
# test cannot leak descendants. Writes the timeout flag file when the limit
# fires, so the caller can tell a timeout (124) from an ordinary failure.
run_with_timeout() {
  local seconds="$1" flag="$2" status=0
  shift 2
  if [ "$seconds" -le 0 ]; then
    "$@"
    return $?
  fi
  rm -f "$flag"
  set -m
  "$@" &
  local command_pid=$!
  set +m
  (
    sleep "$seconds"
    : >"$flag"
    kill -TERM -- -"$command_pid" 2>/dev/null || kill -TERM "$command_pid" 2>/dev/null
    sleep 5
    kill -KILL -- -"$command_pid" 2>/dev/null || kill -KILL "$command_pid" 2>/dev/null
  ) &
  local watcher_pid=$!
  wait "$command_pid" 2>/dev/null || status=$?
  kill "$watcher_pid" 2>/dev/null || true
  wait "$watcher_pid" 2>/dev/null || true
  if [ -e "$flag" ]; then
    return 124
  fi
  return "$status"
}

# The checkout's varde, so scripts that resolve varde from PATH use the working
# tree instead of a stale global install. Sets VARDE_EXEC (the command a wrapper
# execs) and VARDE_LABEL (what the runner prints); returns 1 when none is found.
# Mirrors workflow/tests/lib/varde-bin.sh (checkout_varde), which most test
# scripts call themselves.
resolve_varde() {
  local root="$1" bin
  VARDE_EXEC=""
  VARDE_LABEL=""
  if [ -f "$root/app/pyproject.toml" ] && command -v uv >/dev/null 2>&1; then
    VARDE_EXEC="uv run --project $(printf '%q' "$root/app") varde"
    VARDE_LABEL="$VARDE_EXEC"
    return 0
  fi
  bin="$root/.venv/bin/varde"
  [ -x "$bin" ] || bin="$(command -v varde || true)"
  [ -n "$bin" ] || return 1
  VARDE_EXEC="$(printf '%q' "$bin")"
  VARDE_LABEL="$bin"
}

# install_varde_wrapper <root> <sandbox>: write <sandbox>/bin/varde and report
# which varde the run uses. PATH is only changed inside run_case.
install_varde_wrapper() {
  local root="$1" sandbox="$2"
  if ! resolve_varde "$root"; then
    printf 'varde: none found for %s; scripts use the PATH varde\n' "$root"
    return 0
  fi
  {
    printf '#!/usr/bin/env bash\n'
    printf '# Checkout varde wrapper written by core/scripts/run-shell-tests.sh.\n'
    printf 'exec %s "$@"\n' "$VARDE_EXEC"
  } >"$sandbox/bin/varde"
  chmod +x "$sandbox/bin/varde"
  printf 'varde: %s\n' "$VARDE_LABEL"
}

# Run one labeled test in its own sandbox: run_case <label> <command...>
run_case() {
  local label="$1" status=0 started elapsed
  shift
  started="$(now_seconds)"
  CASE_INDEX=$((CASE_INDEX + 1))
  local sandbox="$SANDBOX_ROOT/sandboxes/$CASE_INDEX" log="$SANDBOX_ROOT/output/$CASE_INDEX.log"
  mkdir -p "$sandbox/home" "$sandbox/config" "$sandbox/data" "$sandbox/tmp"
  (
    export HOME="$sandbox/home" \
      XDG_CONFIG_HOME="$sandbox/config" \
      VARDE_CONFIG_DIR="$sandbox/config/varde" \
      XDG_DATA_HOME="$sandbox/data" \
      XDG_CACHE_HOME="$sandbox/cache" \
      TMPDIR="$sandbox/tmp" \
      UV_OFFLINE=1 \
      PATH="$SANDBOX_ROOT/bin:$PATH"
    run_with_timeout "$CASE_TIMEOUT" "$sandbox/timed-out" "$@"
  ) </dev/null >"$log" 2>&1 || status=$?
  elapsed=$(( $(now_seconds) - started ))

  if [ "$status" -eq 0 ]; then
    printf 'PASS %s (%ss)\n' "$label" "$elapsed"
  else
    if [ "$status" -eq 124 ]; then
      printf 'FAIL %s (timeout after %ss, %ss)\n' "$label" "$CASE_TIMEOUT" "$elapsed"
    else
      printf 'FAIL %s (exit %s, %ss)\n' "$label" "$status" "$elapsed"
    fi
    cat "$log"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  RUN_COUNT=$((RUN_COUNT + 1))
}

# Every script the tier file lets this run run, one root-relative path per line.
run_list() {
  local root="$1" script relative reason
  while IFS= read -r script; do
    [ -n "$script" ] || continue
    relative="${script#"$root"/}"
    if reason="$(skip_reason "$relative")"; then
      continue
    fi
    printf '%s\n' "$relative"
  done < <(discover "$root")
}

list_scripts() {
  local root="$1" script relative reason tier
  while IFS= read -r script; do
    [ -n "$script" ] || continue
    relative="${script#"$root"/}"
    tier="$(tier_of "$relative")"
    if reason="$(skip_reason "$relative")"; then
      printf 'SKIP %s (%s)\n' "$relative" "$reason"
    elif tier_skips "$relative"; then
      printf 'SKIP %s (%s tier; --tier all runs it)\n' "$relative" "$tier"
    else
      printf 'RUN %s (%s)\n' "$relative" "$tier"
    fi
  done < <(discover "$root")
}

run() {
  local root="$1" before after started elapsed
  [ -n "$root" ] || root="$SELF_DIR/../.."
  root="$(cd "$root" && pwd)"
  CASE_TIMEOUT="$2"
  started="$(now_seconds)"
  before="$(fingerprint "$PROTECTED_CONFIG")"

  SANDBOX_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/shell-tests.XXXXXX")"
  mkdir -p "$SANDBOX_ROOT/output" "$SANDBOX_ROOT/sandboxes" "$SANDBOX_ROOT/bin"
  CASE_INDEX=0 RUN_COUNT=0 SKIP_COUNT=0 FAIL_COUNT=0
  install_varde_wrapper "$root" "$SANDBOX_ROOT"

  local script relative reason
  while IFS= read -r script; do
    [ -n "$script" ] || continue
    relative="${script#"$root"/}"
    if reason="$(skip_reason "$relative")"; then
      printf 'SKIP %s (%s)\n' "$relative" "$reason"
      SKIP_COUNT=$((SKIP_COUNT + 1))
      continue
    fi
    if tier_skips "$relative"; then
      printf 'SKIP %s (slow tier; --tier all runs it)\n' "$relative"
      SKIP_COUNT=$((SKIP_COUNT + 1))
      continue
    fi
    run_case "$relative" bash "$script"
  done < <(discover "$root")

  # help-coverage.sh --self-test has no other caller; run it as its own case.
  if [ -f "$root/core/tests/help-coverage.sh" ] && ! tier_skips 'core/tests/help-coverage.sh'; then
    run_case 'core/tests/help-coverage.sh --self-test' \
      bash "$root/core/tests/help-coverage.sh" --self-test
  fi

  after="$(fingerprint "$PROTECTED_CONFIG")"
  elapsed=$(( $(now_seconds) - started ))
  printf '\nsummary: %d run, %d skipped, %d failed (%s tier, %ss)\n' \
    "$RUN_COUNT" "$SKIP_COUNT" "$FAIL_COUNT" "$RUN_TIER" "$elapsed"

  local rc=0
  if [ "$FAIL_COUNT" -ne 0 ]; then
    rc=1
  fi
  if [ "$before" != "$after" ]; then
    printf 'FAIL: protected config changed during the run: %s (%s -> %s)\n' \
      "$PROTECTED_CONFIG" "$before" "$after" >&2
    rc=2
  fi
  return "$rc"
}

require_line() {
  case "$1" in
    *"$2"*) ;;
    *)
      printf 'self-test: %s: output lacks %s\n---\n%s\n' "$3" "$2" "$1" >&2
      exit 1
      ;;
  esac
}

reject_line() {
  case "$1" in
    *"$2"*)
      printf 'self-test: %s: output has %s\n---\n%s\n' "$3" "$2" "$1" >&2
      exit 1
      ;;
    *) ;;
  esac
}

expect_status() {
  local want="$1" label="$2"
  [ "$CHILD_STATUS" -eq "$want" ] || {
    printf 'self-test: %s exited %s, want %s\n---\n%s\n' "$label" "$CHILD_STATUS" "$want" "$CHILD_OUT" >&2
    exit 1
  }
}

# Run any runner script as a child against a scratch root; sets CHILD_STATUS,
# CHILD_OUT.
run_runner() {
  CHILD_STATUS=0
  local runner="$1" root="$2" timeout="$3" protected="$4"
  shift 4
  if CHILD_OUT="$(SHELL_TEST_PROTECTED_CONFIG="$protected" \
    bash "$runner" --root "$root" --timeout "$timeout" "$@" 2>&1)"; then
    CHILD_STATUS=0
  else
    CHILD_STATUS=$?
  fi
}

# Run this runner as a child against a scratch root.
run_child() {
  run_runner "$SELF" "$@"
}

# Run the runner's --list as a child; sets CHILD_STATUS, CHILD_OUT.
run_list_child() {
  CHILD_STATUS=0
  local root="$1" protected="$2"
  shift 2
  if CHILD_OUT="$(SHELL_TEST_PROTECTED_CONFIG="$protected" \
    bash "$SELF" --root "$root" --list "$@" 2>&1)"; then
    CHILD_STATUS=0
  else
    CHILD_STATUS=$?
  fi
}

self_test() {
  local scratch tree tiers own_tree
  SELF_TEST_SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/shell-tests-self.XXXXXX")"
  # Normalize (a TMPDIR ending in / would leave // in the paths the checks
  # compare against, while the child normalizes its own root with cd && pwd).
  scratch="$(cd "$SELF_TEST_SCRATCH" && pwd)"

  # Mixed tree: pass, fail, timeout, two skip classes, and a sandbox assertion.
  tree="$scratch/tree"
  mkdir -p "$tree/mod/tests/lib" "$tree/mod/tests/agents"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$tree/mod/tests/pass.sh"
  printf '#!/usr/bin/env bash\necho boom >&2\nexit 1\n' >"$tree/mod/tests/fail.sh"
  printf '#!/usr/bin/env bash\nsleep 30\n' >"$tree/mod/tests/slow.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$tree/mod/tests/lib/helper.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$tree/mod/tests/agents/agent.sh"
  cat >"$tree/mod/tests/sandbox.sh" <<'EOS'
#!/usr/bin/env bash
case "$HOME" in */sandboxes/*) ;; *) echo "HOME not sandboxed: $HOME" >&2; exit 1 ;; esac
case "$TMPDIR" in */sandboxes/*) ;; *) echo "TMPDIR not sandboxed: $TMPDIR" >&2; exit 1 ;; esac
[ -n "$XDG_CONFIG_HOME" ] && [ -n "$VARDE_CONFIG_DIR" ] && [ -n "$XDG_DATA_HOME" ] || exit 1
EOS

  run_child "$tree" 3 "$scratch/absent.toml"
  [ "$CHILD_STATUS" -ne 0 ] || { printf 'self-test: failing tree exited 0\n' >&2; exit 1; }
  require_line "$CHILD_OUT" 'PASS mod/tests/pass.sh (' 'failing tree seconds'
  require_line "$CHILD_OUT" 'PASS mod/tests/sandbox.sh (' 'env isolation'
  require_line "$CHILD_OUT" 'FAIL mod/tests/fail.sh' 'failing tree'
  require_line "$CHILD_OUT" 'FAIL mod/tests/slow.sh (timeout after 3s,' 'timeout'
  require_line "$CHILD_OUT" 'SKIP mod/tests/lib/helper.sh (sourced test helper)' 'skip list'
  require_line "$CHILD_OUT" 'SKIP mod/tests/agents/agent.sh (run by just test-agents)' 'skip list'
  require_line "$CHILD_OUT" '4 run, 2 skipped, 2 failed' 'summary'

  # Tiers: --list reports each script's tier, --tier fast omits slow scripts, an
  # untiered tree runs everything, and a tier list that does not match the tree
  # (missing, duplicate, stale, or malformed) fails before any script runs.
  tiers="$scratch/tiers.txt"
  printf '# path tier seconds\nmod/tests/pass.sh fast 1\nmod/tests/sandbox.sh fast 1\nmod/tests/fail.sh fast 1\nmod/tests/slow.sh slow 30\n' >"$tiers"
  run_list_child "$tree" "$scratch/absent.toml" --tier all --tiers "$tiers"
  expect_status 0 'tier all list'
  require_line "$CHILD_OUT" 'RUN mod/tests/pass.sh (fast)' 'tier all list'
  require_line "$CHILD_OUT" 'RUN mod/tests/slow.sh (slow)' 'tier all list'
  run_list_child "$tree" "$scratch/absent.toml" --tier fast --tiers "$tiers"
  expect_status 0 'tier fast list'
  require_line "$CHILD_OUT" 'RUN mod/tests/pass.sh (fast)' 'tier fast list'
  require_line "$CHILD_OUT" 'SKIP mod/tests/slow.sh (slow tier; --tier all runs it)' 'tier fast list'
  reject_line "$CHILD_OUT" 'RUN mod/tests/slow.sh' 'tier fast list'
  run_list_child "$tree" "$scratch/absent.toml" --tier fast
  expect_status 0 'untiered list'
  require_line "$CHILD_OUT" 'RUN mod/tests/slow.sh (untiered)' 'untiered list'

  printf 'mod/tests/pass.sh fast 1\nmod/tests/sandbox.sh fast 1\n' >"$scratch/tiers-partial.txt"
  run_child "$tree" 3 "$scratch/absent.toml" --tiers "$scratch/tiers-partial.txt"
  expect_status 2 'untiered script'
  require_line "$CHILD_OUT" 'no entry for mod/tests/fail.sh' 'untiered script'

  printf 'mod/tests/pass.sh fast 1\nmod/tests/pass.sh fast 1\nmod/tests/sandbox.sh fast 1\nmod/tests/fail.sh fast 1\nmod/tests/slow.sh slow 30\n' >"$scratch/tiers-dup.txt"
  run_child "$tree" 3 "$scratch/absent.toml" --tiers "$scratch/tiers-dup.txt"
  expect_status 2 'duplicate tier'
  require_line "$CHILD_OUT" 'duplicate entry for mod/tests/pass.sh' 'duplicate tier'

  printf 'mod/tests/pass.sh fast 1\nmod/tests/sandbox.sh fast 1\nmod/tests/fail.sh fast 1\nmod/tests/slow.sh slow 30\ngone/tests/old.sh fast 1\n' >"$scratch/tiers-stale.txt"
  run_child "$tree" 3 "$scratch/absent.toml" --tiers "$scratch/tiers-stale.txt"
  expect_status 2 'stale tier entry'
  require_line "$CHILD_OUT" 'entry for gone/tests/old.sh is not a script this run would run' 'stale tier entry'

  printf 'mod/tests/pass.sh medium 1\n' >"$scratch/tiers-bad.txt"
  run_child "$tree" 3 "$scratch/absent.toml" --tiers "$scratch/tiers-bad.txt"
  expect_status 2 'bad tier value'
  require_line "$CHILD_OUT" 'tier must be fast or slow: mod/tests/pass.sh medium 1' 'bad tier value'

  run_child "$tree" 3 "$scratch/absent.toml" --tier slow
  expect_status 2 'bad tier name'
  require_line "$CHILD_OUT" 'tier must be fast or all: slow' 'bad tier name'

  # A missing tier file is an error for the runner's own checkout root and for
  # an explicit --tiers; a scratch root without one still runs every script.
  own_tree="$scratch/own"
  mkdir -p "$own_tree/core/scripts" "$own_tree/mod/tests"
  cp "$SELF" "$own_tree/core/scripts/run-shell-tests.sh"
  cp "$SELF_DIR/test-env.sh" "$own_tree/core/scripts/test-env.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$own_tree/mod/tests/pass.sh"
  run_runner "$own_tree/core/scripts/run-shell-tests.sh" "$own_tree" 3 "$scratch/absent.toml"
  expect_status 2 'own root without tier file'
  require_line "$CHILD_OUT" 'not found; add the file or pass --tiers FILE' 'own root without tier file'
  run_child "$own_tree" 3 "$scratch/absent.toml" --tiers "$scratch/no-tiers.txt"
  expect_status 2 'explicit missing tier file'
  require_line "$CHILD_OUT" 'not found; add the file or pass --tiers FILE' 'explicit missing tier file'

  # All-passing tree (the sandbox case still asserts isolation), then --list.
  rm "$tree/mod/tests/fail.sh" "$tree/mod/tests/slow.sh"
  run_child "$tree" 3 "$scratch/absent.toml"
  [ "$CHILD_STATUS" -eq 0 ] || {
    printf 'self-test: passing tree exited %s\n---\n%s\n' "$CHILD_STATUS" "$CHILD_OUT" >&2
    exit 1
  }
  require_line "$CHILD_OUT" 'PASS mod/tests/sandbox.sh' 'passing tree'
  CHILD_OUT="$(SHELL_TEST_PROTECTED_CONFIG="$scratch/absent.toml" bash "$SELF" --root "$tree" --list 2>&1)"
  require_line "$CHILD_OUT" 'RUN mod/tests/pass.sh' 'list mode'
  require_line "$CHILD_OUT" 'SKIP mod/tests/agents/agent.sh (run by just test-agents)' 'list mode'

  # Hidden directories, vendored trees, and nested worktrees are not discovered:
  # each excluded location holds a failing script, so finding one fails the run.
  mkdir -p "$tree/.varde/worktrees/other/mod/tests" "$tree/.hidden/tests" \
    "$tree/linked/tests" "$tree/cloned/tests" "$tree/mod/node_modules/pkg/tests"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/.varde/worktrees/other/mod/tests/fail.sh"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/.hidden/tests/fail.sh"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/mod/node_modules/pkg/tests/fail.sh"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/linked/tests/fail.sh"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/cloned/tests/fail.sh"
  printf 'gitdir: /elsewhere\n' >"$tree/linked/.git"
  mkdir -p "$tree/cloned/.git"
  # A nested repo whose directory name holds glob metacharacters: pruning it
  # needs those escaped, or its failing script is discovered and fails the run.
  mkdir -p "$tree/odd[1]/tests" "$tree/odd[1]/.git"
  printf '#!/usr/bin/env bash\nexit 1\n' >"$tree/odd[1]/tests/fail.sh"
  run_child "$tree" 3 "$scratch/absent.toml"
  expect_status 0 'excluded-tree run'
  require_line "$CHILD_OUT" 'PASS mod/tests/pass.sh' 'excluded tree'
  reject_line "$CHILD_OUT" '.varde/worktrees' 'excluded: .varde worktree'
  reject_line "$CHILD_OUT" '.hidden/' 'excluded: hidden directory'
  reject_line "$CHILD_OUT" 'linked/tests' 'excluded: linked worktree'
  reject_line "$CHILD_OUT" 'cloned/tests' 'excluded: nested clone'
  reject_line "$CHILD_OUT" 'node_modules' 'excluded: vendored tree'
  reject_line "$CHILD_OUT" 'odd' 'excluded: glob-metacharacter name'
  CHILD_OUT="$(SHELL_TEST_PROTECTED_CONFIG="$scratch/absent.toml" bash "$SELF" --root "$tree" --list 2>&1)"
  reject_line "$CHILD_OUT" '.varde/' 'excluded: list mode'

  # The checkout varde wrapper goes first on PATH: a stale varde earlier on the
  # caller's PATH must not win, and the runner reports the varde it chose.
  tree="$scratch/varde"
  mkdir -p "$tree/mod/tests" "$tree/.venv/bin" "$scratch/decoy"
  printf '#!/usr/bin/env bash\necho decoy\n' >"$scratch/decoy/varde"
  chmod +x "$scratch/decoy/varde"
  cat >"$tree/.venv/bin/varde" <<'EOS'
#!/usr/bin/env bash
[ "${1:-}" = --checkout ] && echo 'checkout varde'
EOS
  chmod +x "$tree/.venv/bin/varde"
  cat >"$tree/mod/tests/path-varde.sh" <<'EOS'
#!/usr/bin/env bash
case "$(command -v varde)" in
  */bin/varde) ;;
  *) echo "varde is not the run wrapper: $(command -v varde)" >&2; exit 1 ;;
esac
[ "$(varde --checkout)" = 'checkout varde' ] || { echo 'wrapper did not reach the checkout varde' >&2; exit 1; }
EOS
  PATH="$scratch/decoy:$PATH"
  run_child "$tree" 3 "$scratch/absent.toml"
  PATH="${PATH#"$scratch/decoy:"}"
  expect_status 0 'PATH wrapper run'
  require_line "$CHILD_OUT" "varde: $tree/.venv/bin/varde" 'PATH wrapper line'
  require_line "$CHILD_OUT" 'PASS mod/tests/path-varde.sh' 'PATH wrapper'

  # With app/pyproject.toml and uv on PATH, the wrapper execs the checkout
  # through uv instead of the .venv install, and the runner prints that command.
  tree="$scratch/uv"
  mkdir -p "$tree/app" "$tree/mod/tests" "$scratch/stub-bin"
  printf '[project]\nname = "stub"\n' >"$tree/app/pyproject.toml"
  cat >"$scratch/stub-bin/uv" <<'EOS'
#!/usr/bin/env bash
printf 'uv: %s\n' "$*"
EOS
  chmod +x "$scratch/stub-bin/uv"
  cat >"$tree/mod/tests/uv-varde.sh" <<EOS
#!/usr/bin/env bash
want="uv: run --project $tree/app varde --checkout"
[ "\$(varde --checkout)" = "\$want" ] || {
  echo "wrapper did not exec uv: \$(varde --checkout), want \$want" >&2
  exit 1
}
EOS
  PATH="$scratch/stub-bin:$PATH"
  run_child "$tree" 3 "$scratch/absent.toml"
  PATH="${PATH#"$scratch/stub-bin:"}"
  expect_status 0 'uv wrapper run'
  require_line "$CHILD_OUT" "varde: uv run --project $tree/app varde" 'uv wrapper line'
  require_line "$CHILD_OUT" 'PASS mod/tests/uv-varde.sh' 'uv wrapper'

  # A test that writes to the protected config must fail the run with rc 2.
  tree="$scratch/config"
  mkdir -p "$tree/mod/tests"
  printf 'original\n' >"$scratch/protected.toml"
  cat >"$tree/mod/tests/mutate.sh" <<'EOS'
#!/usr/bin/env bash
printf 'changed\n' >>"$SHELL_TEST_PROTECTED_CONFIG"
EOS
  run_child "$tree" 3 "$scratch/protected.toml"
  expect_status 2 'config guard run'
  require_line "$CHILD_OUT" 'protected config changed during the run' 'config guard'

  # A non-numeric timeout is rejected before any script runs.
  run_child "$tree" abc "$scratch/protected.toml"
  expect_status 2 'bad timeout run'
  require_line "$CHILD_OUT" 'timeout must be a non-negative integer: abc' 'timeout validation'

  printf 'self-test: ok\n'
}

main() {
  local root="" timeout="$DEFAULT_TIMEOUT" list=false tier="all" tiers="" own_root
  while [ $# -gt 0 ]; do
    case "$1" in
      --root) root="${2:?--root needs a directory}"; shift 2 ;;
      --timeout) timeout="${2:?--timeout needs seconds}"; shift 2 ;;
      --tier) tier="${2:?--tier needs fast or all}"; shift 2 ;;
      --tiers) tiers="${2:?--tiers needs a file}"; shift 2 ;;
      --list) list=true; shift ;;
      --self-test) self_test; return 0 ;;
      -h|--help) usage; return 0 ;;
      *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; return 2 ;;
    esac
  done
  case "$tier" in
    fast|all) RUN_TIER="$tier" ;;
    *) printf 'tier must be fast or all: %s\n' "$tier" >&2; return 2 ;;
  esac
  case "$timeout" in
    ''|*[!0-9]*)
      printf 'timeout must be a non-negative integer: %s\n' "$timeout" >&2
      return 2
      ;;
  esac
  [ -n "$root" ] || root="$SELF_DIR/../.."
  root="$(cd "$root" && pwd)"
  own_root="$(cd "$SELF_DIR/../.." && pwd)"
  TIERS_FILE="${tiers:-$root/core/scripts/shell-test-tiers.txt}"
  if [ -f "$TIERS_FILE" ]; then
    load_tiers "$TIERS_FILE"
    validate_tiers "$root"
  elif [ -n "$tiers" ] || [ "$root" = "$own_root" ]; then
    tiers_error "$TIERS_FILE not found; add the file or pass --tiers FILE"
  fi
  if [ "$list" = true ]; then
    list_scripts "$root"
    return 0
  fi
  run "$root" "$timeout"
}

main "$@"
