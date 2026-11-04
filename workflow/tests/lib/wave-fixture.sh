#!/usr/bin/env bash
# Shared scratch repository and helpers for worktree-wave tests.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SCRIPT_DIR/../../core/tests/lib/repo.sh"
source "$SCRIPT_DIR/lib/varde-bin.sh"
WAVE="$(skill_dir varde-orchestrate)/scripts/worktree-wave.sh"
TEST_ROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/worktree-wave.XXXXXX")" && pwd -P)"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export VARDE_REAL_BIN="$(checkout_varde "$REPO_ROOT")"

# Stub varde for the watcher and for ownership checks when no real binary is
# available; a real varde serves check-task-ownership so stray paths are caught.
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/varde" <<STUB
#!/usr/bin/env bash
if [[ "\${1:-} \${2:-}" == "setup watch" ]]; then
  echo "cwd=\$PWD \$*" >> "$TEST_ROOT/calls.log"
  # STUB_WATCH_MODE: nolock, nolockindex (nolock plus an index error), or fail.
  case "\${STUB_WATCH_MODE:-}" in
    nolock) echo "no watcher lock found for this repo set (x)" >&2; exit 1 ;;
    nolockindex) echo "no watcher lock found for this repo set (x); removing code index: boom" >&2; exit 1 ;;
    fail) echo "watcher exploded" >&2; exit 1 ;;
  esac
  exit 0
fi
if [[ "\${1:-}" == plan && "\${2:-}" == check-task-ownership ]]; then
  echo "cwd=\$PWD \$*" >> "$TEST_ROOT/calls.log"
  if [[ -n "\${VARDE_REAL_BIN:-}" ]]; then
    exec "\$VARDE_REAL_BIN" "\$@"
  fi
  echo '{"data":{"status":"ok","stray":[],"declared":[],"changed":[]}}'
  exit 0
fi
echo "unexpected varde invocation: \$*" >&2
exit 2
STUB
chmod +x "$TEST_ROOT/bin/varde"
export PATH="$TEST_ROOT/bin:$PATH"

repo="$TEST_ROOT/repo"
git init -q -b main "$repo"
echo base > "$repo/shared.txt"
mkdir -p "$repo/app"
printf '[project]\nname = "varde"\n' > "$repo/app/pyproject.toml"
git -C "$repo" add shared.txt app/pyproject.toml
git -C "$repo" commit -q -m base
echo '*.ignored' >> "$repo/.git/info/exclude"

# The wave targets the plan branch checked out in the plan worktree.
plan="$repo/.varde/worktrees/plan"
git -C "$repo" worktree add -q -b worktree/plan "$plan" main
cd "$plan"

run() {
  local want="$1" got=0; shift
  "$WAVE" "$@" >"$TEST_ROOT/stdout" 2>"$TEST_ROOT/stderr" || got=$?
  out="$(cat "$TEST_ROOT/stdout" "$TEST_ROOT/stderr")"
  [[ "$got" == "$want" ]] || fail "wave $*: expected exit $want, got $got: $out"
}
wt() { echo "$repo/.varde/worktrees/$1"; }
write_task() { # <file> <modifies...>
  local file="$1"; shift
  mkdir -p "$(dirname "$file")"
  {
    printf -- '---\nstatus: in_progress\ntype: task\n'
    if [[ $# -gt 0 ]]; then
      printf 'modifies:\n'
      printf '  - %s\n' "$@"
    else
      printf 'modifies: []\n'
    fi
    printf -- '---\n'
  } >"$file"
}
commit_in() { # <task> <file> <content>
  echo "$3" > "$(wt "$1")/$2"
  git -C "$(wt "$1")" add "$2"
  git -C "$(wt "$1")" commit -q -m "$1"
}
branch_exists() { git show-ref --verify --quiet "refs/heads/$1"; }
force_clean() {
  git worktree remove --force "$(wt "$1")" 2>/dev/null || true
  git branch -D "worktree/$1" >/dev/null 2>&1 || true
}
has() { grep -q -- "$2" <<<"$1" || fail "$3: missing '$2' in: $1"; }
has_fixed() { grep -Fq -- "$2" <<<"$1" || fail "$3: missing '$2' in: $1"; }
