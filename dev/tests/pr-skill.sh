#!/usr/bin/env bash
set -euo pipefail
source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
FACTS="$(skill_dir varde-pr)/scripts/pr-facts.sh"
CHECKER="$(skill_dir varde-pr)/scripts/check-pr-body.sh"
EVAL="$(skill_dir varde-pr)/evals/verify-pr-eval.sh"
EVALS="$(skill_dir varde-pr)/evals/evals.json"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/pr-skill.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"
export VFAKE_LOG="$TMP/varde.log" GH_LOG="$TMP/gh.log"
cat > "$TMP/bin/varde" <<'FAKE'
#!/usr/bin/env python3
import json
import os
import sys
args = sys.argv[1:]
with open(os.environ["VFAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
def respond(ok, data, code=0):
    print(json.dumps({"ok": ok, "outcome": "success" if ok else "tool-error", "data": data, "meta": {"truncated": False}}))
    raise SystemExit(code)
if args[:2] == ["map", "build"]:
    respond(True, {"dbPath": os.environ["VFAKE_DB"]})
mode = args[1] if len(args) > 1 else ""
query = json.loads(args[args.index("--json") + 1])
if os.environ.get("VFAKE_MODE") == "invalid" and mode == "detect_changes":
    respond(False, {"error": {"code": "invalid_input", "message": "bad range"}}, 1)
if mode == "detect_changes":
    if query.get("diffMode") != "range" or "dbPath" not in query or ".." not in query.get("range", ""):
        respond(False, {"error": {"code": "invalid_input", "message": "range query was not based on the baseline index"}}, 1)
    files = []
    for index in range(12):
        files.append({"file": f"src/file-{index:02}.py", "symbols": [{"name": f"public_{index}", "kind": "function", "change": "modified"}]})
    respond(True, files)
if mode == "blast_radius":
    if os.environ.get("VFAKE_MODE") == "invalid_radius":
        respond(False, {"error": {"code": "invalid_input", "message": "bad file path"}}, 1)
    if os.environ.get("VFAKE_MODE") == "index_missing":
        respond(False, {"error": {"code": "index_missing", "message": "index not found"}}, 1)
    respond(True, {"file": query["filePath"], "results": []})
if mode == "symbol_blast_radius":
    if os.environ.get("VFAKE_MODE") == "index_missing":
        respond(False, {"error": {"code": "index_missing", "message": "index not found"}}, 1)
    respond(True, {"name": query["name"], "blast_radius": []})
respond(False, {"error": {"code": "invalid_input", "message": "unexpected query"}}, 1)
FAKE
cat > "$TMP/bin/gh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_LOG"
FAKE
chmod +x "$TMP/bin/varde" "$TMP/bin/gh"
export VFAKE_DB="$TMP/baseline-index.db"

check_eval_assertions() {
  python3 - "$EVALS" "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path
declared = json.loads(Path(sys.argv[1]).read_text())["evals"]
case = next(item for item in declared if str(item["id"]) == sys.argv[2])
reported = json.loads(Path(sys.argv[3]).read_text())["results"]
assert case["verification_script"] == "evals/verify-pr-eval.sh"
assert {item["assertion"] for item in reported} == set(case["assertions"])
PY
}

seed_repo() {
  local target="$1"
  mkdir -p "$target"
  git -C "$target" init -q
  git -C "$target" config user.name test
  git -C "$target" config user.email test@example.com
  mkdir -p "$target/src"
  printf 'def existing(): return 1\n' > "$target/src/seed.py"
  git -C "$target" add src/seed.py
  git -C "$target" commit -qm seed
  git -C "$target" branch base
  git -C "$target" checkout -qb feature
  for index in $(seq -w 0 11); do
    printf 'def public_%s(): return 2\n' "$index" > "$target/src/file-$index.py"
  done
  git -C "$target" add src/file-*.py
  git -C "$target" commit -qm 'feat: feature work'
  git -C "$target" checkout -q base
  printf 'base only\n' > "$target/base-only.txt"
  git -C "$target" add base-only.txt
  git -C "$target" commit -qm 'fix: base advance'
  git -C "$target" checkout -q feature
}

seed_repo "$TMP/repo"
FACTS_JSON=$(cd "$TMP/repo" && "$FACTS" base feature)
printf '%s\n' "$FACTS_JSON" | jq -e '(.commits | length) == 1 and (.commits[0] | contains("feature work"))' >/dev/null
printf '%s\n' "$FACTS_JSON" | jq -e '.files | length == 12 and (all(.[]; startswith("src/file-")))' >/dev/null
printf '%s\n' "$FACTS_JSON" | jq -e '.truncated == true and .truncatedDetails.files == true and .truncatedDetails.symbols == true' >/dev/null
printf '%s\n' "$FACTS_JSON" | jq -e '(.blastRadius | length) == 10 and (.symbolBlastRadius | length) == 10 and (.detectChanges.data | length) == 12' >/dev/null
jq -s -e 'length == 22 and any(.[]; index("detect_changes") != null) and any(.[]; index("symbol_blast_radius") != null) and all(.[]; .[0] == "map")' "$VFAKE_LOG" >/dev/null
python3 - "$VFAKE_LOG" "$TMP/repo" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
events = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
query = next(json.loads(event[event.index("--json") + 1]) for event in events if "detect_changes" in event)
root = Path(sys.argv[2])
merge_base = subprocess.check_output(["git", "-C", str(root), "merge-base", "base", "feature"], text=True).strip()
assert query["range"] == f"{merge_base}..feature", query
assert Path(query["dbPath"]).name == "baseline-index.db", query
PY

VFAKE_MODE=index_missing
export VFAKE_MODE
NO_INDEX=$(cd "$TMP/repo" && "$FACTS" base feature)
unset VFAKE_MODE
printf '%s\n' "$NO_INDEX" | jq -e '.blastRadiusNote == "blast radius not measured: no index" and ((.blastRadiusError | tostring) | contains("index_missing")) and (.blastRadius | length) == 0 and (.symbolBlastRadius | length) == 0' >/dev/null
VFAKE_MODE=invalid
export VFAKE_MODE
BAD_QUERY=$(cd "$TMP/repo" && "$FACTS" base feature)
unset VFAKE_MODE
printf '%s\n' "$BAD_QUERY" | jq -e '.blastRadiusNote | startswith("blast radius not measured: invalid_input:")' >/dev/null
VFAKE_MODE=invalid_radius
export VFAKE_MODE
BAD_RADIUS=$(cd "$TMP/repo" && "$FACTS" base feature)
unset VFAKE_MODE
printf '%s\n' "$BAD_RADIUS" | jq -e '.blastRadiusNote | startswith("blast radius not measured: blast_radius src/file-00.py: invalid_input:")' >/dev/null
printf '%s\n' "$BAD_RADIUS" | jq -e '(.blastRadiusError | length) == 10 and (.blastRadius | length) == 0' >/dev/null
mkdir -p "$TMP/no-varde-bin"
for command in bash python3 git dirname; do ln -s "$(command -v "$command")" "$TMP/no-varde-bin/$command"; done
NO_VARDE=$(cd "$TMP/repo" && PATH="$TMP/no-varde-bin" "$FACTS" base feature)
printf '%s\n' "$NO_VARDE" | jq -e '.blastRadiusNote == "blast radius not measured: varde is not available on PATH"' >/dev/null

body="$TMP/good.md"
cat > "$body" <<'BODY'
## Summary
Updates the behavior and documents <details> content.

## Evidence
- `uv run pytest`: passed and covers the change.

## Merge Danger
No migration; the checked paths have no data migration.
BODY
"$CHECKER" "$body"
crlf="$TMP/crlf.md"
python3 - "$body" "$crlf" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes().replace(b"\n", b"\r\n"))
PY
"$CHECKER" "$crlf"
fenced="$TMP/fenced.md"
printf '```md\n## Summary\nnot a section\n```\n' > "$fenced"
cat "$body" >> "$fenced"
"$CHECKER" "$fenced"
for bad in missing misordered empty placeholder; do
  case "$bad" in
    missing) printf '## Summary\nText\n\n## Evidence\n`check`\n' > "$TMP/$bad.md"; expected='missing required section: ## Merge Danger' ;;
    misordered) printf '## Evidence\n`check`\n\n## Summary\nText\n\n## Merge Danger\nNone.\n' > "$TMP/$bad.md"; expected='misordered section: ## Evidence; expected ## Summary' ;;
    empty) printf '## Summary\n\n## Evidence\n`check`\n\n## Merge Danger\nNone.\n' > "$TMP/$bad.md"; expected='empty section: ## Summary' ;;
    placeholder) printf '## Summary\n<TODO item>\n\n## Evidence\n`check`\n\n## Merge Danger\nNone.\n' > "$TMP/$bad.md"; expected='placeholder in section: ## Summary' ;;
  esac
  if "$CHECKER" "$TMP/$bad.md" 2>"$TMP/error"; then
    echo "expected $bad body to fail" >&2
    exit 1
  fi
  grep -Fq "$expected" "$TMP/error"
done

mkdir -p "$TMP/output"
export PR_BODY_FILE="$body" PR_OUTPUT_DIR="$TMP/output"
printf 'pr view 4\n' > "$GH_LOG"
EVAL_ID=1 "$EVAL" > "$TMP/eval-read.json"
jq -e 'all(.results[]; .verdict == "PASS")' "$TMP/eval-read.json" >/dev/null
check_eval_assertions 1 "$TMP/eval-read.json"
printf 'pr create --title title --body-file body.md --base main\n' > "$GH_LOG"
EVAL_ID=1 "$EVAL" > "$TMP/eval-write-fail.json"
jq -e 'any(.results[]; .assertion == "No GitHub write command ran" and .verdict == "FAIL")' "$TMP/eval-write-fail.json" >/dev/null
check_eval_assertions 1 "$TMP/eval-write-fail.json"
: > "$GH_LOG"
EVAL_ID=3 "$EVAL" > "$TMP/eval-boundary-pass.json"
jq -e 'all(.results[]; .verdict == "PASS")' "$TMP/eval-boundary-pass.json" >/dev/null
check_eval_assertions 3 "$TMP/eval-boundary-pass.json"
touch "$TMP/output/unrequested.md"
EVAL_ID=3 "$EVAL" > "$TMP/eval-boundary-fail.json"
jq -e 'any(.results[]; .assertion == "Review feedback does not create a PR body file" and .verdict == "FAIL")' "$TMP/eval-boundary-fail.json" >/dev/null
check_eval_assertions 3 "$TMP/eval-boundary-fail.json"
rm -f "$TMP/output/unrequested.md"

: > "$GH_LOG"
"$TMP/bin/gh" pr create --title title --body-file "$body" --base main
EVAL_ID=2 "$EVAL" > "$TMP/eval-publish-pass.json"
jq -e 'all(.results[]; .verdict == "PASS")' "$TMP/eval-publish-pass.json" >/dev/null
check_eval_assertions 2 "$TMP/eval-publish-pass.json"
"$TMP/bin/gh" pr create --title title --body=inline --base main
EVAL_ID=2 "$EVAL" > "$TMP/eval-publish-fail.json"
jq -e 'any(.results[]; .assertion == "gh create does not use inline --body" and .verdict == "FAIL")' "$TMP/eval-publish-fail.json" >/dev/null
check_eval_assertions 2 "$TMP/eval-publish-fail.json"

grep -q '^how: repo-map - ' "$(skill_dir varde-pr)/SKILL.md"
how_topic="$(dirname "$(skill_dir varde-pr)")/../how/varde-pr/repo-map.md"
grep -q 'packs build --stale' "$how_topic"
grep -q 'linked worktree' "$how_topic"

printf 'PASS pr-skill facts, range symbols, error fallbacks, truncation, evals, and body validation\n'
