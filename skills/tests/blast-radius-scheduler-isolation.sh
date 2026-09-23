#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RESOLVER="$SKILLS_DIR/varde-change/scripts/resolve-execution-wave.py"
RUNNER="$SKILLS_DIR/varde-change/scripts/run-parallel-wave.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

repo="$TEST_ROOT/repo"
fake_bin="$TEST_ROOT/bin"
mkdir -p "$repo/src" "$fake_bin"
git -C "$repo" init -q -b main
git -C "$repo" config user.name fixture
git -C "$repo" config user.email fixture@example.test
printf '%s\n' baseline > "$repo/src/seed"
git -C "$repo" add src/seed
git -C "$repo" commit -q -m baseline

cat > "$fake_bin/varde-code" <<'EOF'
#!/usr/bin/env bash
touch "$VARDE_CODE_REBUILT_MARKER"
exit 99
EOF
chmod +x "$fake_bin/varde-code"
export VARDE_CODE_REBUILT_MARKER="$TEST_ROOT/varde-code-rebuilt"

cat > "$TEST_ROOT/manifest.json" <<JSON
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "wave_verification_command": "test -f src/alpha && test -f src/beta",
  "tasks": [
    {
      "id": "alpha",
      "status": "todo",
      "depends_on": [],
      "modifies": ["src/alpha"],
      "creates": [],
      "renames": [],
      "verification_resources": ["impact:src/alpha-consumer"],
      "worker_command": "printf '%s\\n' alpha > src/alpha; git add src/alpha; git commit -q -m alpha"
    },
    {
      "id": "beta",
      "status": "todo",
      "depends_on": [],
      "modifies": ["src/beta"],
      "creates": [],
      "renames": [],
      "verification_resources": ["impact:src/beta-consumer"],
      "worker_command": "printf '%s\\n' beta > src/beta; git add src/beta; git commit -q -m beta"
    }
  ]
}
JSON

wave_json="$(PATH="$fake_bin:$PATH" "$RESOLVER" "$TEST_ROOT/manifest.json")"
jq -e '.parallel_safe == true and .waves[0] == ["alpha", "beta"]' <<< "$wave_json" >/dev/null ||
  fail "precomputed impact resources did not select one wave"

(
  cd "$repo"
  PATH="$fake_bin:$PATH" "$RUNNER" "$TEST_ROOT/manifest.json" \
    --target-ref refs/heads/main --worktree-root "$TEST_ROOT/worktrees"
) >/dev/null ||
  fail "parallel runner failed with precomputed impact resources"

[ ! -e "$VARDE_CODE_REBUILT_MARKER" ] ||
  fail "scheduler rebuilt the code index"
[ -f "$repo/src/alpha" ] && [ -f "$repo/src/beta" ] ||
  fail "integrated wave omitted worker output"

echo "Blast-radius scheduler isolation fixtures passed."
