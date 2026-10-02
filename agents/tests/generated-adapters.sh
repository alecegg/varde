#!/usr/bin/env bash
set -euo pipefail
# Pin the OpenCode adapter generation so results never depend on the host.
export VARDE_AGENTS_OPENCODE_VERSION="${VARDE_AGENTS_OPENCODE_VERSION:-1.4.0}"
OPENCODE_VARIANT=opencode.md
[ "${VARDE_AGENTS_OPENCODE_VERSION%%.*}" -lt 2 ] || OPENCODE_VARIANT=opencode-v2.md

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-agent-generation.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

"$AGENTS_DIR/generate.py" --check

for harness in claude codex opencode pi; do
  destination="$TEST_ROOT/install-$harness"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$destination" -f >/dev/null
  case "$harness" in
    claude) variant="claude.md"; extension="md" ;;
    codex) variant="codex.toml"; extension="toml" ;;
    opencode) variant="$OPENCODE_VARIANT"; extension="md" ;;
    pi) variant="pi.md"; extension="md" ;;
  esac
  for profile in varde-executor varde-explorer varde-planner varde-reviewer; do
    stripped="$TEST_ROOT/$harness-$profile-stripped.$extension"
    # install.sh -f always appends a blank line, the ownership marker, and
    # recorded-default lines; drop them before comparing.
    sed -e '/^<!-- varde-default: /d' -e '/^# varde-default: /d' \
      -e '/^<!-- varde-managed-agent -->$/d' -e '/^# varde-managed-agent$/d' \
      "$destination/$profile.$extension" | sed '$d' >"$stripped"
    cmp "$AGENTS_DIR/$profile/$variant" "$stripped" ||
      fail "$harness installer changed generated $profile output"
  done
done

# Preview and real installation must take the same ownership branch.
parity="$TEST_ROOT/parity"
mkdir -p "$parity"
printf 'local agent\n' >"$parity/varde-planner.md"
before="$(cksum "$parity/varde-planner.md")"
preview="$("$AGENTS_DIR/install.sh" -d "$parity" -a varde-planner -m -n)"
printf '%s\n' "$preview" | grep -Fq "Would preserve unowned $parity/varde-planner.md" ||
  fail "-m preview did not preserve unowned agent"
"$AGENTS_DIR/install.sh" -d "$parity" -a varde-planner -m >/dev/null
[ "$(cksum "$parity/varde-planner.md")" = "$before" ] || fail "-m changed unowned agent"
preview="$("$AGENTS_DIR/install.sh" -d "$parity" -a varde-planner -f -n)"
printf '%s\n' "$preview" | grep -Fq 'Would replace' || fail "-f preview did not report replacement"
[ "$(cksum "$parity/varde-planner.md")" = "$before" ] || fail "-f preview changed agent"
"$AGENTS_DIR/install.sh" -d "$parity" -a varde-planner -f >/dev/null
grep -Fq 'varde-managed-agent' "$parity/varde-planner.md" || fail "-f did not replace agent"
if "$AGENTS_DIR/install.sh" -d "$parity" -a varde-planner -n </dev/null >"$TEST_ROOT/refuse.out" 2>&1; then
  fail "noninteractive preview promised an unavailable replacement"
fi
grep -Fq 'Would refuse noninteractive replacement' "$TEST_ROOT/refuse.out" ||
  fail "noninteractive preview omitted refusal"

# Fail the final move after the old adapter has been backed up. The adapter
# must be restored and the earlier successful item named in the error.
failure="$TEST_ROOT/failure"
mkdir -p "$failure" "$TEST_ROOT/failing-bin"
printf 'previous plan\n<!-- varde-managed-agent -->\n' >"$failure/varde-planner.md"
cat >"$TEST_ROOT/failing-bin/mv" <<'EOF'
#!/usr/bin/env bash
if [ "$2" = "$FAIL_DEST" ] && [ ! -e "$FAIL_ONCE" ]; then
  : >"$FAIL_ONCE"
  exit 17
fi
exec /bin/mv "$@"
EOF
chmod +x "$TEST_ROOT/failing-bin/mv"
if FAIL_DEST="$failure/varde-planner.md" FAIL_ONCE="$TEST_ROOT/mv-failed" \
  PATH="$TEST_ROOT/failing-bin:$PATH" "$AGENTS_DIR/install.sh" -d "$failure" \
  -a varde-explorer,varde-planner -f >"$TEST_ROOT/failure.out" 2>&1; then
  fail "failed adapter replacement returned success"
fi
grep -Fq 'previous plan' "$failure/varde-planner.md" || fail "failed adapter was not restored"
grep -Fq 'varde-managed-agent' "$failure/varde-explorer.md" || fail "earlier adapter did not remain installed"
grep -Fq 'Failed to install varde-planner' "$TEST_ROOT/failure.out" || fail "failed adapter not named"
grep -Fq 'Previously installed: varde-explorer' "$TEST_ROOT/failure.out" || fail "partial result not named"

refusal="$TEST_ROOT/refusal"
mkdir -p "$refusal"
printf 'local plan\n' >"$refusal/varde-planner.md"
if "$AGENTS_DIR/install.sh" -d "$refusal" -a varde-explorer,varde-planner \
  </dev/null >"$TEST_ROOT/refusal.out" 2>&1; then
  fail "noninteractive refusal returned success after an earlier install"
fi
grep -Fq 'Previously installed: varde-explorer' "$TEST_ROOT/refusal.out" ||
  fail "noninteractive refusal omitted prior successful adapter"

copy_failure="$TEST_ROOT/copy-failure"
mkdir -p "$copy_failure" "$TEST_ROOT/copy-failure-bin"
cat >"$TEST_ROOT/copy-failure-bin/cp" <<'EOF'
#!/usr/bin/env bash
for argument in "$@"; do
  if [ "$argument" = "$FAIL_SOURCE" ]; then exit 17; fi
done
exec /bin/cp "$@"
EOF
chmod +x "$TEST_ROOT/copy-failure-bin/cp"
if FAIL_SOURCE="$AGENTS_DIR/varde-planner/claude.md" PATH="$TEST_ROOT/copy-failure-bin:$PATH" \
  "$AGENTS_DIR/install.sh" -d "$copy_failure" -a varde-explorer,varde-planner -f \
  >"$TEST_ROOT/copy-failure.out" 2>&1; then
  fail "adapter copy failure returned success"
fi
[ ! -e "$copy_failure/varde-planner.md" ] || fail "first adapter copy failure left partial destination"
test -f "$copy_failure/varde-explorer.md" || fail "earlier adapter disappeared after copy failure"
grep -Fq 'Previously installed: varde-explorer' "$TEST_ROOT/copy-failure.out" ||
  fail "copy failure omitted prior successful adapter"

drift_root="$TEST_ROOT/drift"
mkdir -p "$drift_root"
for profile in varde-executor varde-explorer varde-planner varde-reviewer; do
  cp -R "$AGENTS_DIR/$profile" "$drift_root/$profile"
done
printf '\n# manual drift\n' >>"$drift_root/varde-planner/codex.toml"

set +e
drift_output="$("$AGENTS_DIR/generate.py" --check --output-root "$drift_root" 2>&1)"
drift_status=$?
set -e
[ "$drift_status" -eq 1 ] || fail "modified adapter passed verification"
printf '%s\n' "$drift_output" | grep -F "stale: varde-planner/codex.toml" >/dev/null ||
  fail "drift output omitted exact changed path"

# Spawn rules: only varde-explorer may be spawned, and only where granted.
python3 - "$AGENTS_DIR" "$OPENCODE_VARIANT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
opencode_variant = sys.argv[2]
spawn_line = (
    "spawn only `varde-explorer` (up to 2 at a time), and only if you have a spawn tool. "
    "otherwise use the brief's explorer notes, then `varde-explore` for gaps."
)


def text(profile, variant):
    return " ".join((root / profile / variant).read_text().lower().split())


def header(profile, variant):
    return (root / profile / variant).read_text().split("---", 2)[1]


for variant in ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md"):
    explorer = text("varde-explorer", variant)
    assert "never spawn agents" in explorer, variant
    assert "spawn only `varde-explorer`" not in explorer, variant
    for profile in ("varde-planner", "varde-executor", "varde-reviewer"):
        body = text(profile, variant)
        assert spawn_line in body, (profile, variant)
        assert "without spawning or delegating" not in body, (profile, variant)
    planner = text("varde-planner", variant)
    assert "if this agent cannot delegate" not in planner, variant
    assert "return to the caller requesting it, and finish only after the caller reports the verdict; never substitute self-review" in planner, variant
    assert "do the task yourself; spawn no agent but `varde-explorer`" in text("varde-executor", variant), variant
    assert "wait for the verdict" not in planner and "wait at the gate" not in text("varde-executor", variant), variant
    reviewer = text("varde-reviewer", variant)
    assert "no agent tool" not in reviewer, variant
    assert "when the read is over budget, report back to the caller to split the review; never split it yourself" in reviewer, variant

for profile in ("varde-planner", "varde-executor", "varde-reviewer", "varde-explorer"):
    grants = profile != "varde-explorer"
    v1 = json.loads(next(l.removeprefix("permission: ") for l in header(profile, "opencode.md").splitlines() if l.startswith("permission: ")))
    v2 = json.loads(next(l.removeprefix("permissions: ") for l in header(profile, "opencode-v2.md").splitlines() if l.startswith("permissions: ")))
    subagent = [(r["resource"], r["effect"]) for r in v2 if r["action"] == "subagent"]
    if grants:
        assert v1["task"] == {"*": "deny", "varde-explorer": "allow"}, profile
        assert subagent == [("*", "deny"), ("varde-explorer", "allow")], profile
    else:
        assert v1["task"] == "deny", profile
        assert subagent == [("*", "deny")], profile
    claude_tools = next(l for l in (root / profile / "claude.md").read_text().splitlines() if l.startswith("tools:"))
    assert not {"Agent", "Task"} & {t.strip() for t in claude_tools.removeprefix("tools:").split(",")}, (profile, claude_tools)
    codex_lines = (root / profile / "codex.toml").read_text().splitlines()
    assert not [l for l in codex_lines if l.startswith("[") or l.split("=")[0].strip() in ("agents", "max_depth", "max_threads", "spawn")], profile
print("Spawn rule assertions passed.")
PY

echo "Generated adapter and installer tests passed."
