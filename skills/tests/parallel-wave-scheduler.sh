#!/usr/bin/env bash
set -euo pipefail

VARDE="${VARDE_BIN:-$(command -v varde)}"
workflow() { "$VARDE" plan "$@"; }
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/wave.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -x "$VARDE" || fail "varde is missing or not executable"

# Blast-radius scenarios live in
# clis/workflow/varde-workflow/tests/execution_wave_scenarios.rs, where a fake
# ImpactQuery replaces the in-process varde map query. The scenarios here never
# reach the impact query (creates-only, nothing ready, or one ready task).

# plan <name>: creates a plan dir inside a repo root with src/ files present.
plan() {
  local dir="$TEST_ROOT/$1"
  mkdir -p "$dir/plan/tasks" "$dir/src"
  git -C "$dir" init -q
  touch "$dir/src/alpha" "$dir/src/beta" "$dir/src/gamma" "$dir/src/delta" \
    "$dir/src/util" "$dir/src/left" "$dir/src/right" "$dir/src/new-alpha"
  git -C "$dir" add src
  printf '%s' "$dir"
}
task() { # task <root> <id> <status> <depends_on> <modifies> [creates] [renames] [verification_resources]
  cat > "$1/plan/tasks/$2.md" <<EOF
---
type: task
status: $3
depends_on: [$4]
modifies: [$5]
creates: [${6:-}]
renames: [${7:-}]
verification_resources: [${8:-}]
kind: ${9:-}
posture: ${10:-}
---
EOF
}
run() { workflow execution-wave --json --repo-root "$1" "${@:2}" "$1/plan" | jq -c .data; }

# A symlink ancestor aliases a not-yet-created destination.
root="$(plan create-alias)"
ln -s src "$root/alias"
task "$root" alpha todo "" "" "src/new/nested.rs"
task "$root" beta todo "" "" "alias/new/nested.rs"
run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/new/nested.rs"]' >/dev/null ||
  fail "symlink aliases of a new destination were parallelized"

# Dangling directory aliases still identify their future target.
root="$(plan dangling-alias)"
ln -s src/future "$root/alias"
task "$root" alpha todo "" "" "src/future/new.rs"
task "$root" beta todo "" "" "alias/new.rs"
run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/future/new.rs"]' >/dev/null ||
  fail "dangling symlink target identity was lost"

# Symlink/.. follows the target's parent, not the link's lexical parent.
root="$(plan symlink-parent)"
mkdir -p "$root/src/deep"
ln -s src/deep "$root/alias"
task "$root" alpha todo "" "" "src/new.rs"
task "$root" beta todo "" "" "alias/../new.rs"
run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/new.rs"]' >/dev/null ||
  fail "symlink parent traversal was normalized lexically"

# Uncertain ownership forces the whole wave serial, including other ready tasks.
for uncertain in loop outside; do
  root="$(plan "uncertain-$uncertain")"
  if [ "$uncertain" = loop ]; then
    ln -s loop "$root/loop"
  else
    mkdir -p "$TEST_ROOT/external"
    ln -s "$TEST_ROOT/external" "$root/outside"
  fi
  task "$root" alpha todo "" "" "$uncertain/new.rs"
  task "$root" beta todo "" "" "src/independent-a.rs"
  task "$root" gamma todo "" "" "src/independent-b.rs"
  run "$root" | jq -e '.next_wave == ["alpha"] and (.reasons | any(contains("ownership path identity is uncertain")))' >/dev/null ||
    fail "uncertain $uncertain ownership allowed a parallel wave"
done

# A missing prefix must not hide a loop, even if later .. would erase it.
for suffix in 'missing/../loop/new.rs' 'missing/../loop/../new.rs' 'hidden/new.rs'; do
  root="$(plan hidden-loop)"
  ln -sf loop "$root/loop"
  ln -sf 'missing/../loop/../real' "$root/hidden"
  task "$root" alpha todo "" "" "$suffix"
  task "$root" beta todo "" "" "src/independent-a.rs"
  task "$root" gamma todo "" "" "src/independent-b.rs"
  run "$root" | jq -e '.next_wave == ["alpha"] and (.reasons | any(contains("ownership path identity is uncertain")))' >/dev/null ||
    fail "missing prefix hid a symlink loop: $suffix"
done
# Dot spellings and an aliased repository root preserve independent creates.
root="$(plan aliased-repo)"
ln -s "$root" "$TEST_ROOT/repo-alias"
task "$root" alpha todo "" "" "./src/../src/new-a.rs"
task "$root" beta todo "" "" "src/new-b.rs"
run "$TEST_ROOT/repo-alias" | jq -e '.next_wave == ["alpha","beta"] and .conflicts == []' >/dev/null ||
  fail "canonical repository aliases serialized independent destinations"
# A ready task must wait when its body points at another task's new file.
root="$(plan new-file-pointer)"
task "$root" a-creator todo "" "" "references/x.md"
task "$root" b-mentions todo "" "src/alpha"
cat >> "$root/plan/tasks/b-mentions.md" <<'EOF'

Use `references/x.md`, which the other task creates.
EOF
run "$root" | jq -e '.next_wave == ["a-creator"] and (.reasons | any(. == "b-mentions: mentions references/x.md created by a-creator; add depends_on"))' >/dev/null ||
  fail "a task mentioning another task's new file was not held out of the wave"

# A rename destination is also a new file pointer, including repo-relative mentions.
root="$(plan renamed-file-pointer)"
task "$root" a-renamer todo "" "" "" "src/old.md -> skills/varde-change/references/y.md"
task "$root" b-mentions todo "" "src/beta"
cat >> "$root/plan/tasks/b-mentions.md" <<'EOF'

Use `skills/varde-change/references/y.md`, which the other task renames.
EOF
run "$root" | jq -e '.next_wave == ["a-renamer"] and (.reasons | any(. == "b-mentions: mentions skills/varde-change/references/y.md created by a-renamer; add depends_on"))' >/dev/null ||
  fail "a task mentioning another task's renamed file was not held out of the wave"
# A spike owns no paths and runs alone, but placement remains isolated.
root="$(plan spike-mode)"
task "$root" spike todo "" "" "" "" "" spike
run "$root" | jq -e '.next_wave == ["spike"] and .wave_mode == "worktree"' >/dev/null ||
  fail "lone spike task did not select isolated mode"
# A missing or blocked dependency is reported, not a silent stall.
root="$(plan deps)"
task "$root" base blocked "" "src/base"
task "$root" needs-base todo "base" "src/x"
task "$root" needs-ghost todo "ghost" "src/y"
run "$root" | jq -e '.ready == [] and (.blocked_by_dep | map(.task + ":" + .reason) | sort) == ["needs-base:blocked","needs-ghost:missing"]' >/dev/null ||
  fail "missing or blocked dependencies were not reported"
# Worker widths above three are accepted.
root="$(plan capped)"
task "$root" alpha todo "" "src/alpha"
run "$root" --max-workers 4 >/dev/null || fail "worker limit above three was rejected"

# Block-style YAML lists parse like inline lists.
root="$(plan block-lists)"
printf -- '---\nstatus: done\ndepends_on: []\nmodifies:\n  - src/alpha\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/alpha.md"
printf -- '---\nstatus: todo\ndepends_on:\n  - alpha\nmodifies:\n  - "src/beta"\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/beta.md"
run "$root" | jq -e '.ready == ["beta"] and (.next_wave | length) <= 1' >/dev/null ||
  fail "block-style lists were misparsed"

# Unindented block-style YAML lists (as task files may carry them) still parse.
root="$(plan unindented-block-lists)"
printf -- '---\nstatus: blocked\ndepends_on: []\nmodifies:\n- src/alpha\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/alpha.md"
printf -- '---\nstatus: todo\ndepends_on:\n- alpha\nmodifies:\n- src/beta\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/beta.md"
result="$(run "$root")"
echo "$result" | jq -e '(.ready | index("beta")) == null and (.next_wave | index("beta")) == null' >/dev/null ||
  fail "unindented block-style depends_on let a blocked dependent through"
echo "$result" | jq -e '[.blocked_by_dep[] | select(.task == "beta" and .dependency == "alpha")] | length == 1' >/dev/null ||
  fail "unindented block-style depends_on did not record beta in blocked_by_dep"

# A dependency cycle is a hard failure.
root="$(plan cycle)"
task "$root" alpha todo "beta" "src/alpha"
task "$root" beta todo "alpha" "src/beta"
set +e
run "$root" >/dev/null 2>&1
status=$?
set -e
[ "$status" -eq 3 ] || fail "cycle exited $status, expected 3"
echo "Parallel wave scheduler fixtures passed."
