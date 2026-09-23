#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$REPO_ROOT/skills/varde-change/scripts/run-parallel-wave.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

new_repo() {
  local root="$1"
  mkdir -p "$root"
  git -C "$root" init -q -b main
  git -C "$root" config user.name fixture
  git -C "$root" config user.email fixture@example.test
  mkdir -p "$root/src"
  printf '%s\n' baseline > "$root/src/seed"
  git -C "$root" add src/seed
  git -C "$root" commit -q -m baseline
}

write_manifest() {
  local root="$1" verification="$2"
  cat > "$root/manifest.json" <<JSON
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "wave_verification_command": "$verification",
  "tasks": [
    {
      "id": "alpha",
      "status": "todo",
      "depends_on": [],
      "modifies": ["src/alpha"],
      "creates": [],
      "renames": [],
      "verification_resources": ["impact:src/alpha-consumer"],
      "worker_command": "sleep 0.2; printf '%s\\n' alpha > src/alpha; git add src/alpha; git commit -q -m alpha"
    },
    {
      "id": "beta",
      "status": "todo",
      "depends_on": [],
      "modifies": ["src/beta"],
      "creates": [],
      "renames": [],
      "verification_resources": ["impact:src/beta-consumer"],
      "worker_command": "sleep 0.2; printf '%s\\n' beta > src/beta; git add src/beta; git commit -q -m beta"
    }
  ]
}
JSON
}

test -x "$RUNNER" || fail "parallel wave runner is missing or not executable"

success_root="$TEST_ROOT/success"
new_repo "$success_root"
write_manifest "$success_root" 'test -f src/alpha && test -f src/beta'
mv "$success_root/manifest.json" "$TEST_ROOT/success-manifest.json"
printf '%s\n' '/ignored-cache/' >> "$success_root/.git/info/exclude"
mkdir -p "$success_root/ignored-cache"
printf '%s\n' retained > "$success_root/ignored-cache/output"
before="$(git -C "$success_root" rev-parse main)"
success_json="$(cd "$success_root" && "$RUNNER" "$TEST_ROOT/success-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/success-worktrees")"
after="$(git -C "$success_root" rev-parse main)"
[ "$before" != "$after" ] || fail "successful integration did not advance target"
[ -f "$success_root/src/alpha" ] || fail "current target checkout missed alpha"
[ -f "$success_root/src/beta" ] || fail "current target checkout missed beta"
[ -f "$success_root/ignored-cache/output" ] ||
  fail "unrelated ignored checkout output was removed"
jq -e '
  .status == "integrated" and
  (.workers | length) == 2 and
  ([.workers[].worktree] | unique | length) == 2 and
  ([.workers[].started_at_ms] | max) < ([.workers[].ended_at_ms] | min) and
  (.recovery_refs | length) == 0
' <<< "$success_json" >/dev/null || fail "successful integration output was unexpected"

failure_root="$TEST_ROOT/failure"
new_repo "$failure_root"
write_manifest "$failure_root" 'false'
mv "$failure_root/manifest.json" "$TEST_ROOT/failure-manifest.json"
failure_before="$(git -C "$failure_root" rev-parse main)"
failure_json="$(cd "$failure_root" && "$RUNNER" "$TEST_ROOT/failure-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/failure-worktrees" || true)"
failure_after="$(git -C "$failure_root" rev-parse main)"
[ "$failure_before" = "$failure_after" ] || fail "failed verification advanced target"
jq -e '
  .status == "failed" and
  (.recovery_refs | length) >= 1 and
  (.error | contains("verification"))
' <<< "$failure_json" >/dev/null || fail "failed integration output omitted recovery state"

while IFS= read -r recovery_ref; do
  git -C "$failure_root" rev-parse --verify "$recovery_ref" >/dev/null ||
    fail "recovery ref was not retained: $recovery_ref"
done < <(jq -r '.recovery_refs[]' <<< "$failure_json")

sed 's/"harness_capacity": 2/"harness_capacity": 1/' \
  "$TEST_ROOT/success-manifest.json" > "$TEST_ROOT/capacity-manifest.json"
capacity_json="$(cd "$success_root" && "$RUNNER" "$TEST_ROOT/capacity-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/capacity-worktrees" || true)"
jq -e '
  (.workers | length) == 0 and
  (.error | contains("capacity"))
' <<< "$capacity_json" >/dev/null || fail "capacity failure started workers or hid capacity"

checkout_root="$TEST_ROOT/checkout-change"
new_repo "$checkout_root"
write_manifest "$checkout_root" 'test -f src/alpha && test -f src/beta'
python3 - "$checkout_root/manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
for task in manifest["tasks"]:
    task["worker_command"] = task["worker_command"].replace("sleep 0.2", "sleep 0.5")
manifest["tasks"][0]["worker_command"] = manifest["tasks"][0][
    "worker_command"
].replace("git add src/alpha", "git add -f src/alpha")
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
PY
printf '%s\n' '/src/alpha' >> "$checkout_root/.git/info/exclude"
mv "$checkout_root/manifest.json" "$TEST_ROOT/checkout-change-manifest.json"
checkout_before="$(git -C "$checkout_root" rev-parse main)"
(
  sleep 0.2
  printf '%s\n' ignored-checkout-output > "$checkout_root/src/alpha"
) &
checkout_editor_pid="$!"
checkout_json="$(cd "$checkout_root" && "$RUNNER" "$TEST_ROOT/checkout-change-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/checkout-change-worktrees" || true)"
wait "$checkout_editor_pid"
[ "$(git -C "$checkout_root" rev-parse main)" = "$checkout_before" ] ||
  fail "checkout change failure advanced target"
[ "$(cat "$checkout_root/src/alpha")" = ignored-checkout-output ] ||
  fail "ignored checkout collision was overwritten"
jq -e '
  .status == "failed" and
  (.error | contains("checkout changed")) and
  (.recovery_refs | length) >= 1
' <<< "$checkout_json" >/dev/null ||
  fail "checkout change failure omitted recovery state"

staging_mutation_root="$TEST_ROOT/staging-mutation"
new_repo "$staging_mutation_root"
write_manifest "$staging_mutation_root" 'test -f src/alpha && test -f src/beta'
python3 - "$staging_mutation_root/manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["wave_verification_command"] = (
    "test -f src/alpha && test -f src/beta"
    "; printf '%s\\n' verification-side-effect > src/verification-side-effect"
)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
PY
mv "$staging_mutation_root/manifest.json" "$TEST_ROOT/staging-mutation-manifest.json"
staging_before="$(git -C "$staging_mutation_root" rev-parse main)"
staging_json="$(cd "$staging_mutation_root" && "$RUNNER" "$TEST_ROOT/staging-mutation-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/staging-mutation-worktrees" || true)"
[ "$(git -C "$staging_mutation_root" rev-parse main)" = "$staging_before" ] ||
  fail "staging mutation failure advanced target"
staging_integration="$(find "$TEST_ROOT/staging-mutation-worktrees" -type d -name integration -print -quit)"
[ -f "$staging_integration/src/verification-side-effect" ] ||
  fail "staging mutation recovery worktree was removed"
jq -e '
  .status == "failed" and
  (.error | contains("staging worktree")) and
  (.recovery_refs | length) >= 1
' <<< "$staging_json" >/dev/null ||
  fail "staging mutation failure omitted recovery state"

scope_escape_root="$TEST_ROOT/scope-escape"
new_repo "$scope_escape_root"
write_manifest "$scope_escape_root" 'test -f src/alpha && test -f src/beta'
python3 - "$scope_escape_root/manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["tasks"][0]["worker_command"] = (
    "printf '%s\\n' alpha > src/alpha"
    "; printf '%s\\n' escape > src/outside"
    "; git add src/alpha src/outside"
    "; git commit -q -m alpha"
)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
PY
mv "$scope_escape_root/manifest.json" "$TEST_ROOT/scope-escape-manifest.json"
scope_before="$(git -C "$scope_escape_root" rev-parse main)"
scope_json="$(cd "$scope_escape_root" && "$RUNNER" "$TEST_ROOT/scope-escape-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/scope-escape-worktrees" || true)"
[ "$(git -C "$scope_escape_root" rev-parse main)" = "$scope_before" ] ||
  fail "scope escape failure advanced target"
jq -e '
  .status == "failed" and
  (.error | contains("undeclared path")) and
  (.recovery_refs | length) >= 1
' <<< "$scope_json" >/dev/null ||
  fail "scope escape failure was not rejected"

linked_target_root="$TEST_ROOT/linked-target"
new_repo "$linked_target_root"
git -C "$linked_target_root" switch -q -c driver
linked_checkout="$TEST_ROOT/linked-target-checkout"
git -C "$linked_target_root" worktree add -q "$linked_checkout" main
write_manifest "$linked_target_root" 'test -f src/alpha && test -f src/beta'
mv "$linked_target_root/manifest.json" "$TEST_ROOT/linked-target-manifest.json"
linked_before="$(git -C "$linked_target_root" rev-parse main)"
linked_json="$(cd "$linked_target_root" && "$RUNNER" "$TEST_ROOT/linked-target-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/linked-target-worktrees" || true)"
[ "$(git -C "$linked_target_root" rev-parse main)" = "$linked_before" ] ||
  fail "linked target rejection advanced target"
[ "$(git -C "$linked_checkout" rev-parse HEAD)" = "$linked_before" ] ||
  fail "linked target checkout was desynchronized"
jq -e '
  .status == "failed" and
  (.error | contains("another linked worktree")) and
  (.workers | length) == 0
' <<< "$linked_json" >/dev/null ||
  fail "linked target checkout was not rejected"

unfinished_root="$TEST_ROOT/unfinished-worker"
new_repo "$unfinished_root"
write_manifest "$unfinished_root" 'test -f src/alpha && test -f src/beta'
printf '%s\n' '/ignored-output/' >> "$unfinished_root/.git/info/exclude"
python3 - "$unfinished_root/manifest.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["tasks"][0]["creates"].append("ignored-output")
manifest["tasks"][0]["worker_command"] += (
    "; mkdir -p ignored-output"
    "; printf '%s\\n' unfinished > ignored-output/extra"
)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
PY
mv "$unfinished_root/manifest.json" "$TEST_ROOT/unfinished-worker-manifest.json"
unfinished_before="$(git -C "$unfinished_root" rev-parse main)"
unfinished_json="$(cd "$unfinished_root" && "$RUNNER" "$TEST_ROOT/unfinished-worker-manifest.json" --target-ref refs/heads/main --worktree-root "$TEST_ROOT/unfinished-worker-worktrees" || true)"
[ "$(git -C "$unfinished_root" rev-parse main)" = "$unfinished_before" ] ||
  fail "unfinished worker advanced target"
unfinished_worktree="$(jq -r '.workers[] | select(.id == "alpha") | .worktree' <<< "$unfinished_json")"
[ -f "$unfinished_worktree/ignored-output/extra" ] ||
  fail "unfinished worker change was not retained"
jq -e '
  .status == "failed" and
  (.error | contains("uncommitted changes")) and
  (.recovery_refs | length) == 2
' <<< "$unfinished_json" >/dev/null ||
  fail "unfinished worker failure omitted recovery state"

echo "Parallel wave integration fixtures passed."
