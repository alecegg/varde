#!/usr/bin/env bash
set -euo pipefail

WORKFLOW="${VARDE_WORKFLOW_BIN:-$(command -v varde-workflow)}"
escalate() { "$WORKFLOW" escalate-deferred "$@"; }
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/escalate-deferred.XXXXXX")"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -x "$WORKFLOW" || fail "varde-workflow is missing or not executable"
export VARDE_CONFIG_DIR="$TEST_ROOT/config"
export VARDE_WORKING_DIR="$TEST_ROOT/working"
export VARDE_KNOWLEDGE_DIR="$TEST_ROOT/knowledge"
mkdir -p "$TEST_ROOT/repo"
git init -q "$TEST_ROOT/repo"
cd "$TEST_ROOT/repo"

working="$TEST_ROOT/working"
deferred="$working/reviews/deferred"
plan="$working/plans/p1"
review="$plan/review-2026-09-01"
mkdir -p "$review" "$deferred"
echo '# Plan' > "$plan/plan.md"

# finding <id> <disposition> [escalated note]
finding() {
  printf '## [%s] Title of %s\n\n**Severity:** medium\n**Label:** triage\n**Disposition:** %s\n**Location:** `src/a.rs:1`\n' "$1" "$1" "$2"
  [ -z "${3:-}" ] || printf '**Escalated:** %s\n' "$3"
  printf '\n### Summary\n\nBody of %s.\n\n```markdown\n## not a heading\n```\n\n### Solutions\n\n1. **Fix it**\n   Do the thing.\n\n' "$1"
}

printf -- '---\ntype: review\ndate: 2026-09-01\nbranch: main\ntarget: abc\nstatus: complete\ncategories:\n  - CORRECTNESS\n  - CODE\ntriage_status: partial\n---\n\n# Review\n' > "$review/review.md"
{ echo '# CORRECTNESS'; echo
  finding CORRECTNESS-001 blank 'scope-creep — spans modules'
  finding CORRECTNESS-002 blank
  finding CORRECTNESS-003 'fix (abc123)' 'human-only — auth'; } > "$review/CORRECTNESS.md"
{ echo '# CODE'; echo; finding CODE-001 blank 'spec-conflict — contradicts spec'; } > "$review/CODE.md"

printf -- '---\ntitle: Deferred\ntype: review\ndate: 2026-08-01\nbranch: main\ntarget: scans\nstatus: complete\ncategories:\n  - SCAN\n  - CORRECTNESS\ntriage_status: complete\n---\n\n# Deferred\n\n## Categories\n\n| Category | Status | Findings |\n|---|---|---:|\n| SCAN | complete | 1 |\n| CORRECTNESS | complete | 2 |\n\nKeep this prose.\n' > "$deferred/review.md"
finding SCAN-001 blank > "$deferred/SCAN.md"
{ finding CORRECTNESS-001 blank; finding CORRECTNESS-004 dismiss; } > "$deferred/CORRECTNESS.md"

snapshot() { (cd "$TEST_ROOT" && find working -type f -exec shasum {} + | sort); }
disposition() { # disposition <file> <id>
  awk -v id="[$2]" 'index($0, "## " id) == 1 {on=1; next} /^## \[/ {on=0} on && /^\*\*Disposition:\*\*/ {print $2; exit}' "$1"
}

# 1. Usage errors exit 2.
set +e
escalate --plan-dir relative --deferred-dir "$deferred" >/dev/null 2>&1; code=$?
set -e
[ "$code" = 2 ] || fail "relative --plan-dir exited $code, want 2"

# 2. The source is marked only after the copy is written: a failed copy leaves it blank.
chmod 555 "$deferred"
if escalate --plan-dir "$plan" --deferred-dir "$deferred" >/dev/null 2>&1; then
  chmod 755 "$deferred"; fail "run with an unwritable deferred review succeeded"
fi
chmod 755 "$deferred"
[ "$(disposition "$review/CORRECTNESS.md" CORRECTNESS-001)" = blank ] || fail "source marked although the copy failed"
[ ! -e "$deferred/CODE.md" ] || fail "failed run created CODE.md"

# 3. First copy: next ID after existing IDs, a new category file, review.md update.
out="$(escalate --plan-dir "$plan" --deferred-dir "$deferred")"
grep -Fxq 'escalated p1/review-2026-09-01 CODE-001 -> deferred CODE-001' <<< "$out" || fail "missing CODE-001 line: $out"
grep -Fxq 'escalated p1/review-2026-09-01 CORRECTNESS-001 -> deferred CORRECTNESS-005' <<< "$out" || fail "missing CORRECTNESS line: $out"
grep -Fxq 'summary: 2 escalated, 0 skipped' <<< "$out" || fail "bad summary: $out"
grep -Fxq '## [CORRECTNESS-005] Title of CORRECTNESS-001' "$deferred/CORRECTNESS.md" || fail "CORRECTNESS-005 heading missing"
grep -Fxq '## [CODE-001] Title of CODE-001' "$deferred/CODE.md" || fail "new CODE.md lacks CODE-001"
[ "$(disposition "$deferred/CORRECTNESS.md" CORRECTNESS-005)" = blank ] || fail "copy Disposition is not blank"
python3 - "$deferred" <<'PY'
import sys
from pathlib import Path
d = Path(sys.argv[1])
copy = (d / "CORRECTNESS.md").read_text().split("## [CORRECTNESS-005]")[1]
for text in ("**Escalated:** scope-creep — spans modules", "**Source:** p1/review-2026-09-01",
             "**Source finding:** CORRECTNESS-001", "### Summary", "## not a heading", "   Do the thing."):
    assert text in copy, f"copy lacks {text!r}"
assert copy.index("**Escalated:**") < copy.index("**Source:**") < copy.index("### Summary")
review = (d / "review.md").read_text()
for text in ("  - CODE\n", "triage_status: partial", "| CORRECTNESS | complete | 3 |",
             "| CODE | complete | 1 |", "| SCAN | complete | 1 |", "Keep this prose."):
    assert text in review, f"review.md lacks {text!r}"
PY
[ "$(disposition "$review/CORRECTNESS.md" CORRECTNESS-001)" = escalated ] || fail "source CORRECTNESS-001 not escalated"
[ "$(disposition "$review/CORRECTNESS.md" CORRECTNESS-002)" = blank ] || fail "non-escalated blank finding changed"
[ "$(disposition "$review/CORRECTNESS.md" CORRECTNESS-003)" = fix ] || fail "decided finding changed"
[ "$(disposition "$review/CODE.md" CODE-001)" = escalated ] || fail "source CODE-001 not escalated"

# 4. A rerun changes nothing.
before="$(snapshot)"
out="$(escalate --plan-dir "$plan" --deferred-dir "$deferred")"
[ "$out" = 'summary: 0 escalated, 0 skipped' ] || fail "rerun output: $out"
[ "$before" = "$(snapshot)" ] || fail "rerun changed files"

# 5. An interrupted run (copy written, source still blank) skips the copy and marks the source.
sed -i.bak 's/^\*\*Disposition:\*\* escalated$/**Disposition:** blank/' "$review/CODE.md" && rm "$review/CODE.md.bak"
before_code="$(shasum "$deferred/CODE.md")"
out="$(escalate --plan-dir "$plan" --deferred-dir "$deferred" --json)"
jq -e '.ok and .data.summary == {"escalated":0,"skipped":1} and .data.findings[0].action == "skipped" and .data.findings[0].deferred_id == "CODE-001"' <<< "$out" >/dev/null ||
  fail "interrupted rerun JSON: $out"
[ "$before_code" = "$(shasum "$deferred/CODE.md")" ] || fail "skip duplicated the copy"
[ "$(disposition "$review/CODE.md" CODE-001)" = escalated ] || fail "skip did not mark the source"

# 6. A malformed finding stops the run before any write.
bad="$working/plans/p2"
mkdir -p "$bad/review-2026-09-02"
echo '# Plan' > "$bad/plan.md"
printf -- '---\ntype: review\nbranch: main\n---\n' > "$bad/review-2026-09-02/review.md"
{ finding STYLE-001 blank 'scope-creep — fine'; finding STYLE-002 blank 'scope-creep — bad severity' |
  sed 's/^\*\*Severity:\*\* medium$/**Severity:** urgent/'; } > "$bad/review-2026-09-02/STYLE.md"
before="$(snapshot)"
set +e
err="$(escalate --plan-dir "$bad" --deferred-dir "$deferred" 2>&1)"; code=$?
set -e
[ "$code" = 1 ] || fail "malformed finding exited $code, want 1"
grep -q 'STYLE-002 Severity' <<< "$err" || fail "malformed report does not name the finding: $err"
[ "$before" = "$(snapshot)" ] || fail "malformed run changed files"

echo "escalate-deferred: copy, ID allocation, new category, rerun, interrupted skip, ordering, and malformed input pass."
