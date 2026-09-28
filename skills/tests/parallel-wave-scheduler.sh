#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RESOLVER="$SKILLS_DIR/varde-change/scripts/resolve-execution-wave.py"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/wave.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -x "$RESOLVER" || fail "execution-wave resolver is missing or not executable"

# Fake varde-code: blast radius comes from $TEST_ROOT/radius/<path with / as _>.
fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin" "$TEST_ROOT/radius"
cat > "$fake_bin/varde-code" <<'EOF'
#!/usr/bin/env bash
path="$(printf '%s' "$3" | jq -r .filePath)"
file="$RADIUS_DIR/$(printf '%s' "$path" | tr / _)"
if [ -f "$file" ]; then data="$(cat "$file")"; else data='[]'; fi
printf '{"ok":true,"data":%s}\n' "$data"
EOF
chmod +x "$fake_bin/varde-code"
export RADIUS_DIR="$TEST_ROOT/radius"
radius() { printf '%s' "$2" > "$RADIUS_DIR/$(printf '%s' "$1" | tr / _)"; }

# plan <name>: creates a plan dir inside a repo root with src/ files present.
plan() {
  local dir="$TEST_ROOT/$1"
  mkdir -p "$dir/plan/tasks" "$dir/src"
  touch "$dir/src/alpha" "$dir/src/beta" "$dir/src/gamma" "$dir/src/delta" \
    "$dir/src/util" "$dir/src/left" "$dir/src/right" "$dir/src/new-alpha"
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
---
EOF
}
run() { PATH="$fake_bin:$PATH" "$RESOLVER" --repo-root "$1" "${@:2}" "$1/plan"; }

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
if python3 -c 'import os; raise SystemExit(not hasattr(os.path, "ALLOW_MISSING"))'; then
  run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/future/new.rs"]' >/dev/null ||
    fail "dangling symlink target identity was lost"
else
  run "$root" | jq -e '.next_wave == ["alpha"] and (.reasons | any(contains("ownership path identity is uncertain")))' >/dev/null ||
    fail "older Python did not serialize the unresolved symlink"
fi

# Symlink/.. follows the target's parent, not the link's lexical parent.
root="$(plan symlink-parent)"
mkdir -p "$root/src/deep"
ln -s src/deep "$root/alias"
task "$root" alpha todo "" "" "src/new.rs"
task "$root" beta todo "" "" "alias/../new.rs"
run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/new.rs"]' >/dev/null ||
  fail "symlink parent traversal was normalized lexically"

# Existing modifications and both rename endpoints share canonical ownership.
root="$(plan rename-alias)"
ln -s src "$root/alias"
radius src/alpha '["src/alpha-test"]'
task "$root" alpha-renamer todo "" "" "" "alias/alpha -> alias/new.rs"
task "$root" beta-source todo "" "src/alpha"
task "$root" gamma-target todo "" "" "src/new.rs"
run "$root" | jq -e '.next_wave == ["alpha-renamer"] and ([.conflicts[].files[]] | sort) == ["src/alpha","src/new.rs"]' >/dev/null ||
  fail "aliased rename source or destination did not conflict"
rm -f "$RADIUS_DIR"/*

# Relative and absolute aliases returned by the graph use the same identity.
root="$(plan graph-alias)"
ln -s src "$root/alias"
task "$root" alpha todo "" "alias/alpha"
task "$root" beta todo "" "src/beta"
radius src/beta '["src/beta-test"]'
for graph_path in alias/beta "$root/alias/beta"; do
  radius src/alpha "[\"$graph_path\"]"
  run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/beta"]' >/dev/null ||
    fail "graph aliases did not conflict with canonical writes"
done
rm -f "$RADIUS_DIR"/*

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

# Unknown graph identity retains the existing conservative serial fallback.
root="$(plan uncertain-graph)"
ln -s loop "$root/loop"
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "" "src/new.rs"
radius src/alpha '["loop/graph.rs"]'
run "$root" | jq -e '.next_wave == ["alpha"] and (.reasons | any(contains("blast_radius failed")))' >/dev/null ||
  fail "uncertain graph identity was treated as independent"
rm -f "$RADIUS_DIR"/*

# Dot spellings and an aliased repository root preserve independent creates.
root="$(plan aliased-repo)"
ln -s "$root" "$TEST_ROOT/repo-alias"
task "$root" alpha todo "" "" "./src/../src/new-a.rs"
task "$root" beta todo "" "" "src/new-b.rs"
run "$TEST_ROOT/repo-alias" | jq -e '.next_wave == ["alpha","beta"] and .conflicts == []' >/dev/null ||
  fail "canonical repository aliases serialized independent destinations"

# Simulate older Python without modifying the interpreter's shared os.path.
root="$(plan older-python)"
ln -s src "$root/alias"
ln -s src/future "$root/dangling"
RESOLVER="$RESOLVER" FIXTURE_ROOT="$root" python3 -B - <<'PY'
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("wave", os.environ["RESOLVER"])
wave = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave)
wave.os = SimpleNamespace(path=SimpleNamespace())
root = Path(os.environ["FIXTURE_ROOT"]).resolve()
assert wave.canonical_path(root, "alias/nested/new.rs") == "src/nested/new.rs"
assert wave.canonical_path(root, "alias/../new.rs") == "new.rs"
for uncertain in ["dangling/new.rs", "missing/../src/new.rs"]:
    try:
        wave.canonical_path(root, uncertain)
    except ValueError:
        pass
    else:
        raise AssertionError(f"older Python accepted uncertain path: {uncertain}")
tasks = {
    task: {"status": "todo", "depends_on": [], "writes": [owned], "graph_sources": [],
           "missing_ownership": [], "verification_resources": []}
    for task, owned in [("alpha", "dangling/new.rs"), ("beta", "src/a.rs"), ("gamma", "src/b.rs")]
}
assert wave.resolve(tasks, root, 3)["next_wave"] == ["alpha"]
PY

# Independent ready tasks run as one wave; a dependent task waits.
root="$(plan independent)"
radius src/alpha '["src/alpha-test"]'
radius src/beta '["src/beta-test"]'
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "src/beta"
task "$root" follow-up todo "alpha, beta" "src/gamma"
[ "$(run "$root" | jq '.next_wave | length')" -ge 2 ] || fail "independent tasks did not form a parallel-safe wave"
run "$root" | jq -e '.next_wave == ["alpha","beta"] and .ready == ["alpha","beta"] and (has("strategy") | not)' >/dev/null ||
  fail "independent wave was unexpected"

# A shared import that neither task writes does not conflict.
root="$(plan shared-import)"
radius src/alpha '["src/util"]'
radius src/beta '["src/util"]'
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "src/beta"
[ "$(run "$root" | jq '.next_wave | length')" -ge 2 ] || fail "shared read-only import serialized the wave"
rm -f "$RADIUS_DIR"/*

# Both ends of a rename are owned paths, including the rename source.
root="$(plan rename-source)"
radius src/alpha '["src/alpha-test"]'
radius src/gamma '["src/gamma-test"]'
radius src/new-alpha '["src/new-alpha-test"]'
task "$root" renamer todo "" "" "" "src/alpha -> src/new-alpha"
task "$root" source-writer todo "" "src/alpha"
task "$root" target-writer todo "" "src/new-alpha"
run "$root" | jq -e '(.next_wave | length) <= 1 and ([.conflicts[].files[]] | sort) == ["src/alpha","src/new-alpha"]' >/dev/null ||
  fail "rename source and destination did not conflict with other writes"
rm -f "$RADIUS_DIR"/*

# Tasks with distinct files but shared verification state run in separate waves.
root="$(plan shared-verification-resource)"
radius src/alpha '["src/alpha-test"]'
radius src/beta '["src/beta-test"]'
task "$root" alpha todo "" "src/alpha" "" "" "db:integration-snapshot"
task "$root" beta todo "" "src/beta" "" "" "db:integration-snapshot"
run "$root" | jq -e '(.next_wave | length) <= 1 and .conflicts[0].resources == ["db:integration-snapshot"]' >/dev/null ||
  fail "shared verification resource did not serialize the wave"
rm -f "$RADIUS_DIR"/*

# Old task metadata without every ownership field stays on serial execution.
root="$(plan missing-ownership)"
radius src/alpha '["src/alpha-test"]'
radius src/beta '["src/beta-test"]'
printf -- '---\nstatus: todo\ndepends_on: []\nmodifies: [src/alpha]\ncreates: []\n---\n' > "$root/plan/tasks/alpha.md"
task "$root" beta todo "" "src/beta"
run "$root" | jq -e '.next_wave == ["alpha"]' >/dev/null ||
  fail "missing ownership metadata did not force serial execution"
rm -f "$RADIUS_DIR"/*

# Writing into another task's blast radius serializes them. varde-code
# returns absolute paths; the resolver compares them repo-relative.
root="$(plan conflict)"
radius src/left "[\"$root/src/right\"]"
radius src/right '["src/right-test"]'
task "$root" left todo "" "src/left"
task "$root" right todo "" "src/right"
[ "$(run "$root" | jq '.next_wave | length')" -le 1 ] || fail "blast-radius conflict did not fall back to serial"
run "$root" | jq -e '.next_wave == ["left"] and .conflicts[0].files == ["src/right"]' >/dev/null ||
  fail "conflict was not reported"
rm -f "$RADIUS_DIR"/*

# Reverse-only impact still catches conflicts when the consumer sorts first.
root="$(plan reverse-impact)"
radius src/alpha '["src/alpha-test"]'
radius src/beta '["src/alpha"]'
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "src/beta"
run "$root" | jq -e '.next_wave == ["alpha"] and .conflicts[0].files == ["src/alpha"]' >/dev/null ||
  fail "reverse-only impact missed a dependency conflict with consumer first"
rm -f "$RADIUS_DIR"/*

# A task with no declared write set never runs in parallel.
root="$(plan unknown)"
radius src/alpha '["src/alpha-test"]'
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" ""
[ "$(run "$root" | jq '.next_wave | length')" -le 1 ] || fail "empty write set was parallelized"

# An empty blast radius is unknown (maybe an unindexed language), not independent.
root="$(plan no-edges)"
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "src/beta"
[ "$(run "$root" | jq '.next_wave | length')" -le 1 ] || fail "empty blast radius was treated as independent"

# A missing or blocked dependency is reported, not a silent stall.
root="$(plan deps)"
task "$root" base blocked "" "src/base"
task "$root" needs-base todo "base" "src/x"
task "$root" needs-ghost todo "ghost" "src/y"
run "$root" | jq -e '.ready == [] and (.blocked_by_dep | map(.task + ":" + .reason) | sort) == ["needs-base:blocked","needs-ghost:missing"]' >/dev/null ||
  fail "missing or blocked dependencies were not reported"

# Waves are capped at three workers.
root="$(plan capped)"
for id in alpha beta gamma delta; do radius "src/$id" "[\"src/$id-test\"]"; task "$root" "$id" todo "" "src/$id"; done
run "$root" | jq -e '(.next_wave | length) == 3' >/dev/null ||
  fail "wave exceeded three workers"
if run "$root" --max-workers 4 >/dev/null 2>&1; then
  fail "worker limit above three was accepted"
fi

rm -f "$RADIUS_DIR"/*

# Without varde-code, every wave is serial.
root="$(plan no-cli)"
task "$root" alpha todo "" "src/alpha"
task "$root" beta todo "" "src/beta"
no_cli_path="$TEST_ROOT/nocli"
mkdir -p "$no_cli_path"
for tool in python3 git env; do ln -sf "$(command -v "$tool")" "$no_cli_path/$tool"; done
[ "$(PATH="$no_cli_path" "$RESOLVER" --repo-root "$root" "$root/plan" | jq '.next_wave | length')" -le 1 ] ||
  fail "missing varde-code did not fall back to serial"

# Block-style YAML lists parse like inline lists.
root="$(plan block-lists)"
printf -- '---\nstatus: done\ndepends_on: []\nmodifies:\n  - src/alpha\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/alpha.md"
printf -- '---\nstatus: todo\ndepends_on:\n  - alpha\nmodifies:\n  - "src/beta"\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/beta.md"
run "$root" | jq -e '.ready == ["beta"] and (.next_wave | length) <= 1' >/dev/null ||
  fail "block-style lists were misparsed"

# Unindented block-style YAML lists (as varde-workflow transition writes them) still parse.
root="$(plan unindented-block-lists)"
printf -- '---\nstatus: blocked\ndepends_on: []\nmodifies:\n- src/alpha\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/alpha.md"
printf -- '---\nstatus: todo\ndepends_on:\n- alpha\nmodifies:\n- src/beta\ncreates: []\nrenames: []\nverification_resources: []\n---\n' > "$root/plan/tasks/beta.md"
result="$(run "$root")"
echo "$result" | jq -e '(.ready | index("beta")) == null and (.next_wave | index("beta")) == null' >/dev/null ||
  fail "unindented block-style depends_on let a blocked dependent through"
echo "$result" | jq -e '[.blocked_by_dep[] | select(.task == "beta" and .dependency == "alpha")] | length == 1' >/dev/null ||
  fail "unindented block-style depends_on did not record beta in blocked_by_dep"

# Continuing after a failure schedules only ready, independent work. Once that
# work finishes, the blocked task and its dependent remain pending; after the
# blocked task succeeds on a later run, its dependent becomes ready.
root="$(plan continue-after-blocked)"
radius src/beta '["src/beta-test"]'
radius src/gamma '["src/gamma-test"]'
radius src/delta '["src/delta-test"]'
task "$root" failed blocked "" "src/alpha"
task "$root" waiting todo "failed" "src/beta"
task "$root" independent-a todo "" "src/gamma"
task "$root" independent-b todo "" "src/delta"
result="$(run "$root")"
echo "$result" | jq -e '.ready == ["independent-a","independent-b"] and .next_wave == ["independent-a","independent-b"] and .blocked_by_dep == [{"task":"waiting","dependency":"failed","reason":"blocked"}]' >/dev/null ||
  fail "continuation scheduled work that depends on a blocked task"
task "$root" independent-a done "" "src/gamma"
task "$root" independent-b done "" "src/delta"
result="$(run "$root")"
echo "$result" | jq -e '.ready == [] and .next_wave == [] and .blocked_by_dep == [{"task":"waiting","dependency":"failed","reason":"blocked"}]' >/dev/null ||
  fail "completed independent work hid the still-blocked task or dependent"
task "$root" failed done "" "src/alpha"
result="$(run "$root")"
echo "$result" | jq -e '.ready == ["waiting"] and .next_wave == ["waiting"] and .blocked_by_dep == []' >/dev/null ||
  fail "dependent did not become ready after the blocked task succeeded on resume"
rm -f "$RADIUS_DIR"/*

# A dependency cycle is a hard failure.
root="$(plan cycle)"
task "$root" alpha todo "beta" "src/alpha"
task "$root" beta todo "alpha" "src/beta"
set +e
run "$root" >/dev/null 2>&1
status=$?
set -e
[ "$status" -eq 3 ] || fail "cycle exited $status, expected 3"

# The shipped task template's frontmatter is what the resolver parses.
root="$(plan template)"
awk '/^````/{n++; next} n==1' "$SKILLS_DIR/varde-change/assets/TASK-TEMPLATE.md" |
  sed -e 's/depends_on: \["<dep-id>"\]/depends_on: []/' \
    -e 's|^modifies: \[\]|modifies: [src/alpha]|' > "$root/plan/tasks/from-template-alpha.md"
awk '/^````/{n++; next} n==1' "$SKILLS_DIR/varde-change/assets/TASK-TEMPLATE.md" |
  sed -e 's/depends_on: \["<dep-id>"\]/depends_on: []/' \
    -e 's|^modifies: \[\]|modifies: [src/beta]|' > "$root/plan/tasks/from-template-beta.md"
radius src/alpha '["src/alpha-test"]'
radius src/beta '["src/beta-test"]'
run "$root" | jq -e '.next_wave == ["from-template-alpha","from-template-beta"]' >/dev/null ||
  fail "resolver does not parse complete ownership from the task template"

echo "Parallel wave scheduler fixtures passed."
