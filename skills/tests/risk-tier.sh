#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_SKILLS="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/risk-tier.XXXXXX")"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -f "$REAL_SKILLS/shared/scripts/risk-tier.py" || fail "risk-tier.py is missing"

# A fixture skills/ tree carries its own copy of risk-tier.py and skill-flow.py
# so signal evaluation never touches the real repo's skills/tests inventory or
# a live varde-code index.
fixtures="$TEST_ROOT/skills"
mkdir -p "$fixtures/varde-change/scripts" "$fixtures/varde-agent-doc-authoring/scripts" "$fixtures/tests"
cp "$REAL_SKILLS/shared/scripts/risk-tier.py" "$fixtures/varde-change/scripts/risk-tier.py"
cp "$REAL_SKILLS/varde-agent-doc-authoring/scripts/skill-flow.py" \
   "$fixtures/varde-agent-doc-authoring/scripts/skill-flow.py"

run() {
  ( cd "$TEST_ROOT" && python3 -B "skills/varde-change/scripts/risk-tier.py" "$@" )
}

# check_tier <desc> <expected tier> <expected signal, or "" for none> <scope-path...>
# Env-var-prefixed calls (`RISK_TIER_CASE=x PATH=... check_tier ...`) scope
# that env to this one invocation.
check_tier() {
  local desc="$1" tier="$2" signal="$3"; shift 3
  local out got
  out="$(run "$@")"
  got="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['tier'])" "$out")"
  [[ "$got" == "$tier" ]] || fail "$desc: expected tier $tier, got $out"
  if [[ -n "$signal" ]]; then
    python3 -c "import json,sys; sys.exit(0 if sys.argv[1] in json.loads(sys.argv[2])['signals'] else 1)" \
      "$signal" "$out" || fail "$desc: expected signal '$signal' in $out"
  fi
}

assert_clean() {
  local desc="$1"; shift
  local out
  out="$(run "$@")"
  [[ "$out" == '{"tier": "low", "signals": [], "evidence": {}}' ]] \
    || fail "$desc: expected empty low-tier output, got $out"
}

# --- Directory-scope fail-safety --------------------------------------------

# A bare `skills` scope that can't resolve to one skill, and (at this point
# in the fixture) contains no skill directory to expand into either, must
# not silently fall through to a signal-free low tier (friction 16).
check_tier "bare skills directory with no contained skill stays high" high \
  scope_not_individually_classified skills

# --- Code-scope fixtures ---------------------------------------------------

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
cat > "$fake_bin/varde-code" <<'FAKE'
#!/usr/bin/env bash
mode="$1"
case "$mode" in
  blast_radius)
    case "${RISK_TIER_CASE:-}" in
      dependent_outside_scope) echo '{"ok":true,"data":["code/out-of-scope.py"]}' ;;
      *) echo '{"ok":true,"data":[]}' ;;
    esac
    ;;
  nav_map)
    case "${RISK_TIER_CASE:-}" in
      foundational_file)
        echo '{"ok":true,"data":{"foundational_files":[{"file":"code/scope-a.py","dependents":10,"count":20}]}}' ;;
      *) echo '{"ok":true,"data":{"foundational_files":[]}}' ;;
    esac
    ;;
  clusters)
    case "${RISK_TIER_CASE:-}" in
      multi_cluster_scope)
        echo '{"ok":true,"data":{"clusters":[{"id":1,"files":["code/scope-a.py"]},{"id":2,"files":["code/scope-b.py"]}]}}' ;;
      *) echo '{"ok":true,"data":{"clusters":[{"id":1,"files":["code/scope-a.py","code/scope-b.py"]}]}}' ;;
    esac
    ;;
  *) echo '{"ok":false}'; exit 1 ;;
esac
FAKE
chmod +x "$fake_bin/varde-code"

RISK_TIER_CASE=dependent_outside_scope PATH="$fake_bin:$PATH" \
  check_tier "dependent-outside-scope" high dependent_outside_scope code/scope-a.py

RISK_TIER_CASE=foundational_file PATH="$fake_bin:$PATH" \
  check_tier "foundational-file" high foundational_file code/scope-a.py

RISK_TIER_CASE=multi_cluster_scope PATH="$fake_bin:$PATH" \
  check_tier "multi-cluster" high multi_cluster_scope code/scope-a.py code/scope-b.py

# varde-code missing from PATH entirely.
PATH="/usr/bin:/bin" check_tier "varde-code unavailable" high varde_code_unavailable code/scope-a.py

# varde-code on PATH but a query fails (nonzero exit).
fail_bin="$TEST_ROOT/bin-fail"
mkdir -p "$fail_bin"
printf '#!/usr/bin/env bash\nexit 1\n' > "$fail_bin/varde-code"
chmod +x "$fail_bin/varde-code"
PATH="$fail_bin:$PATH" check_tier "varde-code query failure" high varde_code_unavailable code/scope-a.py

# Clean scope, varde-code available: tier low, no signals.
RISK_TIER_CASE=clean PATH="$fake_bin:$PATH" assert_clean "clean code scope" code/scope-a.py code/scope-b.py

# --- Text-fallback (git grep) fixtures --------------------------------------
# varde-code unavailable, but a real git checkout backs the text fallback.
git_root="$TEST_ROOT/git-fallback"
mkdir -p "$git_root/code" "$git_root/skills/varde-change/scripts"
cp "$REAL_SKILLS/shared/scripts/risk-tier.py" "$git_root/skills/varde-change/scripts/risk-tier.py"
( cd "$git_root" && git init -q && git config user.email t@example.com && git config user.name t )

printf 'def solo():\n    pass\n' > "$git_root/code/solo.py"
printf 'def another():\n    pass\n' > "$git_root/code/second.py"
printf 'def referenced():\n    pass\n' > "$git_root/code/referenced.py"
printf 'from code.referenced import referenced\n' > "$git_root/code/other.py"
( cd "$git_root" && git add -A && git commit -q -m fixture )

run_git() {
  ( cd "$git_root" && PATH="/usr/bin:/bin" python3 -B "skills/varde-change/scripts/risk-tier.py" "$@" )
}

field() {
  python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])[sys.argv[2]]))" "$1" "$2"
}

out="$(run_git code/solo.py)"
[[ "$(field "$out" tier)" == '"low"' ]] || fail "self-contained code file: expected low tier, got $out"
[[ "$(field "$out" signals)" == '[]' ]] || fail "self-contained code file: expected no signals, got $out"
python3 -c "import json,sys; sys.exit(0 if 'varde_code_unavailable' in json.loads(sys.argv[1])['evidence'] else 1)" \
  "$out" || fail "self-contained code file: expected varde_code_unavailable in evidence, got $out"

out="$(run_git code/referenced.py)"
[[ "$(field "$out" tier)" == '"high"' ]] || fail "stem mentioned elsewhere: expected high tier, got $out"
python3 -c "
import json, sys
data = json.loads(sys.argv[1])
assert 'dependent_outside_scope' in data['signals'], data
detail = data['evidence']['dependent_outside_scope'][0]
assert detail.get('source') == 'text-fallback', data
" "$out" || fail "stem mentioned elsewhere: expected dependent_outside_scope with source text-fallback, got $out"

out="$(run_git code/solo.py code/second.py)"
[[ "$(field "$out" tier)" == '"high"' ]] || fail "two code files: expected high tier, got $out"
python3 -c "import json,sys; sys.exit(0 if 'multi_file_scope_unverified' in json.loads(sys.argv[1])['signals'] else 1)" \
  "$out" || fail "two code files: expected multi_file_scope_unverified, got $out"

# --- Skill-doc fixtures -----------------------------------------------------

# skill_reach_external: SKILL.md dispatches inline to a sibling skill.
mkdir -p "$fixtures/varde-fixture-a/references" "$fixtures/varde-fixture-b/references"
cat > "$fixtures/varde-fixture-a/SKILL.md" <<'EOF'
---
name: varde-fixture-a
description: "Fixture skill A."
---

# Fixture skill A

Read the request, then open the matching reference.

## Entry routing

| The request is | Read |
|---|---|
| Do the fixture thing | `references/route-a.md` |

Explicit intent wins: for cross-skill work → `varde-fixture-b mode-x`.
EOF
cat > "$fixtures/varde-fixture-a/references/route-a.md" <<'EOF'
# Route A

Some reference content for route A.
EOF
cat > "$fixtures/varde-fixture-b/SKILL.md" <<'EOF'
---
name: varde-fixture-b
description: "Fixture sibling skill."
---

# Fixture skill B

## Entry routing

| The request is | Read |
|---|---|
| Handle mode x | `references/mode-x.md` |
EOF
cat > "$fixtures/varde-fixture-b/references/mode-x.md" <<'EOF'
# Mode X

Some reference content for mode x.
EOF

check_tier "skill-doc reach leaves skill" high skill_reach_external \
  skills/varde-fixture-a/SKILL.md

# Installed-copy resolution: an on-PATH risk-tier.py, installed outside the
# analyzed repo, must still resolve skill-flow.py and skills/tests/* from the
# analyzed repo's cwd, not from its own installed location.
installed="$TEST_ROOT/installed/scripts"
mkdir -p "$installed"
cp "$REAL_SKILLS/shared/scripts/risk-tier.py" "$installed/risk-tier.py"
out="$(cd "$TEST_ROOT" && python3 -B "$installed/risk-tier.py" skills/varde-fixture-a/SKILL.md)"
[[ "$out" == "$(run skills/varde-fixture-a/SKILL.md)" ]] \
  || fail "installed copy: expected same result as the in-repo copy, got $out"

# shared_file: any path under skills/shared/, and a skill's copy of a file
# skills/shared/MANIFEST lists for that skill.
mkdir -p "$fixtures/shared/references" "$fixtures/varde-fixture-f/references"
cat > "$fixtures/shared/MANIFEST" <<'EOF'
references/review-gates.md varde-fixture-f
EOF
printf 'Shared review-gate content.\n' > "$fixtures/shared/references/review-gates.md"
cp "$fixtures/shared/references/review-gates.md" \
   "$fixtures/varde-fixture-f/references/review-gates.md"

check_tier "shared file under skills/shared/" high shared_file \
  skills/shared/references/review-gates.md

check_tier "skill's MANIFEST-listed copy of a shared file" high shared_file \
  skills/varde-fixture-f/references/review-gates.md

assert_clean "unrelated file stays low despite skills/shared/ existing" \
  skills/varde-fixture-b/references/mode-x.md

# vendored_copy_exists: a MANIFEST-listed reference with a byte-identical
# sibling copy under another skill's references/.
cat > "$fixtures/tests/vendored-copies.sh" <<'EOF'
MANIFEST=(
  "shared-ref.md:*"
)
EOF
mkdir -p "$fixtures/varde-fixture-c/references" "$fixtures/varde-fixture-d/references"
printf 'Shared vendored content.\n' > "$fixtures/varde-fixture-c/references/shared-ref.md"
cp "$fixtures/varde-fixture-c/references/shared-ref.md" "$fixtures/varde-fixture-d/references/shared-ref.md"

check_tier "byte-identical vendored copy" high vendored_copy_exists \
  skills/varde-fixture-c/references/shared-ref.md

# named_by_test_file: a file under skills/tests/ names the changed file.
mkdir -p "$fixtures/varde-fixture-c/scripts"
printf "print('hi')\n" > "$fixtures/varde-fixture-c/scripts/helper.py"
printf '# exercises helper.py\n' > "$fixtures/tests/helper-test.sh"

check_tier "named by a test file" high named_by_test_file \
  skills/varde-fixture-c/scripts/helper.py

# Clean skill-doc scope: no dispatch, no manifest entry, no naming test file.
assert_clean "clean skill-doc scope" skills/varde-fixture-b/references/mode-x.md

# In-skill-only routing: an entry-routing table that only points at the
# skill's own references/, with no cross-skill dispatch, inline mode, or
# unresolved pointer, must stay low.
mkdir -p "$fixtures/varde-fixture-e/references"
cat > "$fixtures/varde-fixture-e/SKILL.md" <<'EOF'
---
name: varde-fixture-e
description: "Fixture skill E."
---

# Fixture skill E

Read the request, then open the matching reference.

## Entry routing

| The request is | Read |
|---|---|
| Do the fixture thing | `references/route-e.md` |
EOF
cat > "$fixtures/varde-fixture-e/references/route-e.md" <<'EOF'
# Route E

Some reference content for route E.
EOF

assert_clean "in-skill-only routing stays low" skills/varde-fixture-e/SKILL.md

echo "risk-tier: code and skill-doc high-tier triggers, varde-code unavailability, and clean low-tier scopes pass."
