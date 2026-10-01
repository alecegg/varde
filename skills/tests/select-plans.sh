#!/usr/bin/env bash
set -euo pipefail

# select-plans.py filters, orders, and reports cycles with a fake varde-workflow.

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SKILLS_DIR/varde-change/scripts/select-plans.py"
dir="${TMPDIR:-/tmp}/select-plans.$$"
mkdir -p "$dir"
trap 'rm -rf "$dir"' EXIT
W="$dir/working"
FX="$dir/fx"
BIN="$dir/bin"
mkdir -p "$W/plans" "$FX" "$BIN" "$dir/empty"

fail() { echo "FAIL: $1"; [ -z "${2:-}" ] || echo "$2"; exit 1; }

plan() { # id status [shape] [extra body]
  mkdir -p "$W/plans/$1"
  printf -- '---\nstatus: %s\ntitle: "Title %s"\ntype: plan\nshape: %s\n---\n# x\n%s\n' \
    "$2" "$1" "${3:-single}" "${4:-}" >"$W/plans/$1/plan.md"
}

plan 2026-02-b backlog
plan 2026-01-a backlog
plan 2026-01-act active
plan 2026-01-done completed
plan 2026-01-x-draft backlog
plan 2026-01-oq backlog single $'## Open Questions\n\n- Which shape?'
plan 2026-01-oq-empty backlog single $'## Open Questions\n\nNone.\n\n## Design'
mkdir -p "$W/plans/group/child"
plan group backlog group
plan group/child/2026-03-nested backlog
plan 2026-01-blocked backlog
plan 2026-01-cyc-x backlog
plan 2026-01-cyc-y backlog

ready='{"data":{"blockers":[],"implementation_ready":true,"planning_ready":true}}'
cat >"$FX/2026-01-blocked.readiness.json" <<'J'
{"data":{"blockers":[{"artifact_id":"2026-01-blocked","code":"dependency_incomplete","dependency":"z","status":"backlog"}],"implementation_ready":false,"planning_ready":false}}
J
cat >"$FX/2026-02-b.readiness.json" <<'J'
{"data":{"blockers":[],"implementation_ready":false,"planning_ready":true,"review":{"blockers":[{"code":"review_missing"}]}}}
J
# The cycle appears only in the second candidate's graph.
cat >"$FX/2026-01-cyc-y.graph.json" <<'J'
{"data":{"blockers":[{"artifact_id":"2026-01-cyc-y","code":"dependency_cycle","dependency":"2026-01-cyc-x","status":null}]}}
J

cat >"$BIN/varde-workflow" <<'FAKE'
#!/usr/bin/env bash
# Serves fixtures; graph without --all is an error, as pagination would hide cycles.
verb="$1"; plan_file="$2"; shift 2
echo "$verb $*" >>"$FX/calls.log"
id="$(basename "$(dirname "$plan_file")")"
if [ "$verb" = graph ]; then
  case " $* " in *" --all "*) ;; *) echo "graph needs --all" >&2; exit 2 ;; esac
  default='{"data":{"blockers":[]}}'
else
  default='{"data":{"blockers":[],"implementation_ready":true,"planning_ready":true}}'
fi
file="$FX/$id.$verb.json"
if [ -f "$file" ]; then cat "$file"; else echo "$default"; fi
FAKE
chmod +x "$BIN/varde-workflow"

export FX
PY="$(command -v python3)"
out="$(PATH="$BIN:$PATH" python3 "$SCRIPT" --working "$W")" || fail "script failed" "$out"
check() { python3 -c "import json,sys; d=json.loads(sys.stdin.read()); $1" <<<"$out" || fail "$2" "$out"; }

check 'assert [p["id"] for p in d["plans"]] == ["2026-01-a","2026-01-oq-empty","2026-02-b","2026-03-nested","2026-01-act"]' "order or filter"
check 'assert d["excluded_by_dependency"] == 3' "excluded_by_dependency (blocked + two cycle plans)"
check 'assert d["cycles"] == ["2026-01-cyc-x","2026-01-cyc-y"]' "cycles from second candidate"
check 'assert d["degraded"] is False' "degraded set with workflow"
check 'p = [p for p in d["plans"] if p["id"]=="2026-02-b"][0]; assert p["implementation_ready"] is False and p["blockers"] == [{"code":"review_missing"}] and p["title"] == "Title 2026-02-b"' "review blocker kept selectable"
graphs="$(grep -c '^graph' "$FX/calls.log")"
[ "$graphs" -eq 8 ] || fail "expected one graph call per candidate (8), got $graphs"
[ "$(grep '^graph' "$FX/calls.log" | grep -vc -- '--all')" -eq 0 ] || fail "graph call without --all"

out="$(PATH="$dir/empty" "$PY" "$SCRIPT" --working "$W" 2>&1)" || fail "degraded run failed" "$out"
check 'assert d["degraded"] is True and d["cycles"] == [] and d["excluded_by_dependency"] == 0' "degraded flags"
check 'assert [p["id"] for p in d["plans"]][:2] == ["2026-01-a","2026-01-blocked"] and len(d["plans"]) == 8' "degraded lists candidates"

# Degraded mode filters by depends_on (inline and block lists).
W2="$dir/working2"
mkdir -p "$W2/plans"
dplan() { # id status depends_on-lines
  mkdir -p "$W2/plans/$1"
  printf -- '---\nstatus: %s\ntitle: "T %s"\ntype: plan\nshape: single\n%s\n---\n# x\n' \
    "$2" "$1" "${3:-}" >"$W2/plans/$1/plan.md"
}
dplan dep-done completed
dplan dep-open backlog
dplan inline-ok backlog 'depends_on: [dep-done]'
dplan inline-bad backlog 'depends_on: [dep-done, dep-open]'
dplan block-ok backlog $'depends_on:\n  - dep-done'
dplan block-bad backlog $'depends_on:\n  - dep-done\n  - dep-open'
dplan no-deps backlog 'depends_on: []'
out="$(PATH="$dir/empty" "$PY" "$SCRIPT" --working "$W2" 2>&1)" || fail "degraded deps run failed" "$out"
check 'assert sorted(p["id"] for p in d["plans"]) == ["block-ok","dep-open","inline-ok","no-deps"], d["plans"]' "degraded dependency filter"
check 'assert d["excluded_by_dependency"] == 2 and d["degraded"] is True and len(d["degraded_plans"]) == 6' "degraded counts and plans"

# Degraded mode resolves depends_on as <plan_dir>/../<dep>/plan.md, with no id fallback.
W3="$dir/working3"
pplan() { # relative-dir status depends_on-line
  mkdir -p "$W3/plans/$1"
  printf -- '---\nstatus: %s\ntitle: "T %s"\ntype: plan\nshape: single\n%s\n---\n# x\n' \
    "$2" "$1" "${3:-}" >"$W3/plans/$1/plan.md"
}
pplan group/child completed
pplan group/open-child backlog
pplan dep-done completed
pplan uses-path backlog 'depends_on: [group/child]'
pplan uses-open backlog 'depends_on: [group/open-child]'
pplan group/nested backlog 'depends_on: [dep-done]'
pplan group/sib completed
pplan group/nested-ok backlog 'depends_on: [sib]'
out="$(PATH="$dir/empty" "$PY" "$SCRIPT" --working "$W3" 2>&1)" || fail "degraded path deps run failed" "$out"
check 'assert sorted(p["id"] for p in d["plans"]) == ["nested-ok","open-child","uses-path"], d["plans"]' "degraded path-form dependency resolution"

# Degraded mode reads dependencies that resolve outside <working>/plans.
W4="$dir/working4"
mkdir -p "$W4/plans/in-open" "$W4/plans/in-done" "$W4/plans/in-missing" "$W4/ext-done" "$W4/ext-open"
ext() { printf -- '---\nstatus: %s\ntitle: "T"\ntype: plan\nshape: single\n---\n# x\n' "$2" >"$W4/$1/plan.md"; }
ext ext-done completed
ext ext-open active
for n in in-open:ext-open in-done:ext-done in-missing:ext-gone; do
  printf -- '---\nstatus: backlog\ntitle: "T"\ntype: plan\nshape: single\ndepends_on: [../%s]\n---\n# x\n' "${n#*:}" >"$W4/plans/${n%%:*}/plan.md"
done
out="$(PATH="$dir/empty" "$PY" "$SCRIPT" --working "$W4" 2>&1)" || fail "degraded outside deps run failed" "$out"
check 'assert [p["id"] for p in d["plans"]] == ["in-done"], d["plans"]' "degraded dependency outside plans dir"

# One failed graph call degrades only that plan.
cat >"$FX/inline-ok.graph.json" <<'J'
not json
J
rm -f "$FX/calls.log"
out="$(PATH="$BIN:$PATH" python3 "$SCRIPT" --working "$W2")" || fail "partial degrade run failed" "$out"
check 'assert d["degraded_plans"] == ["inline-ok"], d["degraded_plans"]' "only failed plan degraded"
check 'assert sorted(p["id"] for p in d["plans"]) == ["block-bad","block-ok","dep-open","inline-bad","inline-ok","no-deps"], d["plans"]' "other plans keep readiness, failed plan filtered by deps"
[ "$(grep -c '^readiness' "$FX/calls.log")" -eq 5 ] || fail "readiness skipped for healthy plans"

if python3 "$SCRIPT" --working "$dir/none" >/dev/null; then fail "missing working dir should exit 1"; fi
echo "ok"
