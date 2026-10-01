#!/usr/bin/env bash
# skill-flow.py maps routes, chains, unreferenced files, and missing targets,
# and completes on every shipped skill.
set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLOW="$SKILLS_DIR/varde-agent-doc-authoring/scripts/skill-flow.py"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

tmp="$(mktemp -d "${TMPDIR:-/tmp}/skill-flow.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

# Fixture: one routed reference that always loads a second (a chain), plus an
# unreferenced asset.
skill="$tmp/flow-fixture"
mkdir -p "$skill/references" "$skill/assets"
cat > "$skill/SKILL.md" <<'EOF'
---
name: flow-fixture
description: Fixture skill.
---
# Fixture

| The request is | Read |
|---|---|
| Build a thing | `references/build.md` |
EOF
cat > "$skill/references/build.md" <<'EOF'
# Build

1. Read `references/detail.md` for the steps.
2. When it fails, read `references/recover.md`.
EOF
printf 'Detail words here.\n' > "$skill/references/detail.md"
printf 'Recovery steps for a failed build.\n' > "$skill/references/recover.md"
printf 'Unused.\n' > "$skill/assets/unused.md"

report="$(python3 "$FLOW" "$skill")" || fail "clean fixture exited non-zero"
grep -qF 'Build a thing' <<<"$report" || fail "route row missing: $report"
grep -qF '    references/detail.md (~5)' <<<"$report" || fail "transitive file missing"
grep -qF 'chain: references/detail.md <- references/build.md' <<<"$report" \
  || fail "chain not reported"
grep -qF 'unreferenced: assets/unused.md' <<<"$report" || fail "unreferenced not reported"
echo "Routes, chain, and unreferenced file reported."

# --write: references form a longest-prefix tree with token estimates and routes.
files="$tmp/files-fixture"
mkdir -p "$files/references" "$files/scripts"
cat > "$files/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Build route | `references/build.md` |
| Guide route | `references/build-guide.md` |
| Deep route | `references/build-guide-deep.md` |
| Debug route | `references/build-posture-debug.md` |
| Other route | `references/other.md` |
EOF
printf 'build root words\nRun `scripts/run.sh` to build.\n' > "$files/references/build.md"
printf 'echo run\n' > "$files/scripts/run.sh"
printf 'guide words\n' > "$files/references/build-guide.md"
printf 'deepest words\n' > "$files/references/build-guide-deep.md"
printf 'debug path words\n' > "$files/references/build-posture-debug.md"
printf 'other path words\n' > "$files/references/other.md"
printf 'unused path words\n' > "$files/references/unentered.md"

python3 -B "$FLOW" --write "$files" >/dev/null
doc="$(cat "$files/FLOW.md")"
files_at="$(grep -n '^## Files$' <<<"$doc" | cut -d: -f1 || true)"
routes_at="$(grep -n '^## Routes$' <<<"$doc" | cut -d: -f1 || true)"
[ -n "$files_at" ] && [ "$files_at" -lt "$routes_at" ] \
  || fail "Files tree missing near the top of FLOW.md: $doc"
grep -qF -- '- SKILL.md (~67 tok; routes: Build route, Guide route, Deep route, Debug route, Other route)' \
  <<<"$doc" || fail "SKILL.md lacks its count or routes: $doc"
grep -qF -- '- references/build.md (~12 tok; routes: Build route)' <<<"$doc" \
  || fail "root reference lacks its count or route: $doc"
grep -qF -- '  - references/build-guide.md (~3 tok; routes: Guide route)' <<<"$doc" \
  || fail "build-guide.md is not nested under build.md: $doc"
grep -qF -- '    - references/build-guide-deep.md (~4 tok; routes: Deep route)' <<<"$doc" \
  || fail "deepest prefix parent was not selected: $doc"
grep -qF -- '  - references/build-posture-debug.md (~5 tok; routes: Debug route)' <<<"$doc" \
  || fail "build-posture-debug.md is not nested under build.md: $doc"
grep -qF -- '- references/other.md (~5 tok; routes: Other route)' <<<"$doc" \
  || fail "other root reference lacks its route: $doc"
grep -qF -- '- references/unentered.md (~5 tok; routes: -)' <<<"$doc" \
  || fail "unentered reference missing from tree: $doc"
grep -q ' words[;)]' <<<"$doc" && fail "FLOW.md still reports word counts: $doc"
grep -qF 'scripts/run.sh"]' <<<"$doc" || fail "script node label is not the bare path: $doc"
! grep -Eq 'scripts/[^"]*\(~[0-9]+ tok' <<<"$doc" || fail "script node shows a size: $doc"
python3 -B "$FLOW" --json "$files" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
assert set(d) == {"skill", "tokens", "references", "edges", "external",
                  "routes", "structure", "findings"}, d.keys()
' || fail "--json shape changed"
echo "FLOW.md Files tree nests references, counts tokens, and lists entering routes."

mermaid="$(python3 "$FLOW" --mermaid "$skill")"
grep -qx 'flowchart TD' <<<"$mermaid" || fail "no flowchart header"
grep -qF '(["Build a thing"])' <<<"$mermaid" || fail "no route node"
grep -qF 'references/detail.md (~5 tok)' <<<"$mermaid" || fail "no token-count label"
grep -qF -- '-->|"Build / step 1: Read references/detail.md for the steps."|' <<<"$mermaid" \
  || fail "edge not labeled with its step: $mermaid"
grep -qF -- '-.->|"Build / step 2: When it fails, read references/recove..."|' <<<"$mermaid" \
  || fail "conditional edge not dotted: $mermaid"
python3 "$FLOW" --json "$skill" | python3 -c '
import json, sys
r = json.load(sys.stdin)[0]["routes"][0]
assert r["min_tokens"] < r["max_tokens"], r
' || fail "min cost does not skip the conditional load"
echo "Mermaid output has route nodes, token counts, edge labels, and dotted conditional edges."

# A pointer to a nonexistent file exits 1 and names the target.
printf '\nSee `references/gone.md`.\n' >> "$skill/references/build.md"
set +e
report="$(python3 "$FLOW" "$skill")"
status=$?
set -e
[ "$status" -eq 1 ] || fail "missing target exited $status, want 1"
grep -qF 'missing: references/build.md:6 -> references/gone.md' <<<"$report" \
  || fail "missing target not reported: $report"
echo "Missing target exits 1."

# Shared files: shared/references/x.md stands in for a skill's own missing file
# when shared/MANIFEST lists that skill, but only for skills it lists.
shared_root="$tmp/shared-fixture"
listed="$shared_root/listed-skill"
unlisted="$shared_root/unlisted-skill"
mkdir -p "$listed/references" "$unlisted/references" "$shared_root/shared/references"
printf 'references/x.md listed-skill\n' > "$shared_root/shared/MANIFEST"
printf 'Shared words here for x.\n' > "$shared_root/shared/references/x.md"
for skill_dir in "$listed" "$unlisted"; do
  cat > "$skill_dir/SKILL.md" <<'EOF'
---
name: shared-user
description: Fixture skill.
---
# Fixture

| The request is | Read |
|---|---|
| Use x | `references/x.md` |
EOF
done

report="$(python3 "$FLOW" "$listed")" || fail "shared pointer exited non-zero"
grep -qF 'missing' <<<"$report" && fail "listed skill still reports missing: $report"
grep -qF '    references/x.md' <<<"$report" || fail "shared file's tokens missing from route: $report"
echo "A MANIFEST-listed shared file resolves with no missing finding."

set +e
report="$(python3 "$FLOW" "$unlisted")"
status=$?
set -e
[ "$status" -eq 1 ] || fail "unlisted skill's missing shared file exited $status, want 1"
grep -qF 'missing: SKILL.md' <<<"$report" || fail "unlisted skill did not report missing: $report"
echo "A skill not listed in MANIFEST still reports the file missing."

# Classification rules: sibling skills where varde-flow calls varde-other inline
# and through an executor dispatch.
pair="$tmp/pair"
flow_skill="$pair/skills/varde-flow"
other_skill="$pair/skills/varde-other"
mkdir -p "$flow_skill/references" "$other_skill/references" "$pair/agents/varde-executor"
cat > "$flow_skill/SKILL.md" <<'EOF'
# Rules

Before implementation edits, apply `references/gate.md`.
Always read `references/base.md`.

| The request is | Read |
|---|---|
| Do the work | `references/work.md` |
| Other thing | `references/other.md` |
EOF
cat > "$flow_skill/references/work.md" <<'EOF'
# Work

1. Read `references/step.md`.
2. The file `references/aside.md` holds history.
3. Then continue with `references/next.md`.
4. Run `varde-other check` for the final pass.
5. Run `varde-other check` again after fixes.
6. Run `varde-other missing` last.
7. Dispatch one `executor` round of `varde-other check`.
8. Use `references/redirect.md` instead, regardless of scope.
9. Follow `references/compare.md` instead of guessing.

- **Broken build:** load `references/label.md`.

## Unmerged isolated checkout

Read `references/heading.md`.
EOF
for name in gate base other step aside next label heading redirect compare; do
  printf 'Body of %s.\n' "$name" > "$flow_skill/references/$name.md"
done
cat > "$other_skill/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Check the result | `references/check.md` |
| Large thing | `references/large.md` |
EOF
printf 'Check steps.\n' > "$other_skill/references/check.md"
printf 'Large %s\n' {1..200} > "$other_skill/references/large.md"
printf -- '---\nname: varde-executor\nskills: varde-other\n---\n# Executor\n' \
  > "$pair/agents/varde-executor/claude.md"

python3 -B "$FLOW" --json "$flow_skill" | python3 -c '
import json, sys
from pathlib import Path
pair = Path(sys.argv[1])
def size(path):
    return -(-len(path.read_text()) // 4)
d = json.load(sys.stdin)[0]
edge = {e["to"].split("/")[-1]: e for e in d["edges"] if e["from"] == "references/work.md"}
work, other = d["routes"]
own = d["tokens"]
check = size(pair / "skills/varde-other/SKILL.md") + size(pair / "skills/varde-other/references/check.md")
checks = {
    "plain mention is not a load": edge["aside.md"]["kind"] == "mention",
    "hand-off is its own kind": edge["next.md"]["kind"] == "handoff",
    "label bullet is a conditional load": edge["label.md"]["kind"] == "load"
        and edge["label.md"]["conditional"],
    "heading case is conditional": edge["heading.md"]["conditional"],
    "plain step is an unconditional load": not edge["step.md"]["conditional"],
    "preamble is not a route": [r["route"] for r in d["routes"]] == ["Do the work", "Other thing"],
    "preamble loads reach every route": all(
        {"references/gate.md", "references/base.md"} <= set(r["files"]) for r in d["routes"]),
    "edit-gated preamble load is max only": all(
        "references/gate.md" not in r["min_files"] for r in d["routes"]),
    "plain preamble load is in min": all(
        "references/base.md" in r["min_files"] for r in d["routes"]),
    "own min is SKILL, base, work, step and compare": work["min_tokens"] == sum(
        own[f] for f in ["SKILL.md", "references/base.md", "references/work.md",
                         "references/step.md", "references/compare.md"]),
    "hand-off and mention stay out of max": not {
        "references/next.md", "references/aside.md"} & set(work["files"]),
    "hand-off listed": sorted(work["handoffs"]) == sorted(
        ["references/next.md", "references/redirect.md"]),
    "redirect instead is a hand-off": edge["redirect.md"]["kind"] == "handoff",
    "redirect excluded from files": "references/redirect.md" not in work["files"],
    "comparison instead of stays a load": edge["compare.md"]["kind"] == "load",
    "comparison stays in files": "references/compare.md" in work["files"],
    "inline mode resolved by entry stem, once": work["inline"] == [
        {"target": "varde-other check", "resolved": "varde-other: Check the result"}],
    "main min adds the inline route once": work["main_min_tokens"] == work["min_tokens"] + check,
    "no largest-route fallback": work["unresolved"] == ["varde-other missing"],
    "other route has no calls": other["main_max_tokens"] == other["max_tokens"]
        and other["dispatches"] == [],
}
disp = work["dispatches"]
definition = size(pair / "agents/varde-executor/claude.md")
checks["dispatch is a separate line item"] = len(disp) == 1 and disp[0]["agent"] == "executor" \
    and disp[0]["runs"] == "varde-other: Check the result" \
    and disp[0]["from"] == ["references/work.md:9"] and not disp[0]["conditional"]
checks["dispatch cost is definition, preload and route, each once"] = \
    disp[0]["min_tokens"] == definition + check
bad = [name for name, ok in checks.items() if not ok]
assert not bad, (bad, json.dumps(d, indent=1))
' "$pair" || fail "classification rules"
mermaid="$(python3 -B "$FLOW" --mermaid "$flow_skill")"
grep -qF '==>|"Work / step 3: Then continue with references/next.md."|' <<<"$mermaid" \
  || fail "hand-off not drawn thick: $mermaid"
grep -qF '[["varde-other check"]]' <<<"$mermaid" || fail "inline mode node missing: $mermaid"
grep -qF '[["agent: executor"]]' <<<"$mermaid" || fail "dispatch node missing: $mermaid"
grep -qF 'aside.md"' <<<"$(grep -- '-->\|-.->' <<<"$mermaid")" \
  && fail "mention drawn as an edge: $mermaid"
report="$(python3 -B "$FLOW" "$flow_skill")"
grep -qF 'inline: varde-other check -> varde-other: Check the result' <<<"$report" \
  || fail "inline mode missing from text report: $report"
grep -qF 'dispatch executor: varde-other: Check the result, ~' <<<"$report" \
  || fail "dispatch missing from text report: $report"
python3 -B "$FLOW" --write "$flow_skill" >/dev/null || true
grep -qF '| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |' \
  "$flow_skill/FLOW.md" || fail "FLOW.md lacks main, subagent, and lookups columns"
grep -qE '^\| Do the work \| .* \| executor ~[0-9]+ \|' "$flow_skill/FLOW.md" \
  || fail "FLOW.md lacks the per-dispatch cost: $(cat "$flow_skill/FLOW.md")"
# Real repo: dispatch cost must include the agents/varde-reviewer definition.
# A copy without agents/ silently drops it, so the difference is its cost.
bare="$tmp/bare-skills"
mkdir -p "$bare"
cp -R "$SKILLS_DIR/varde-change" "$SKILLS_DIR/varde-review" "$bare/"
python3 -B "$FLOW" --json "$SKILLS_DIR/varde-change" >"$tmp/real.json"
python3 -B "$FLOW" --json "$bare/varde-change" >"$tmp/bare.json" || true  # exits 1: sibling skills absent
python3 -c '
import json, sys
from pathlib import Path
def reviews(path):
    d = json.load(open(path))[0]
    return [x["min_tokens"] for r in d["routes"] for x in r["dispatches"] if x["agent"] == "review"]
real, bare = reviews(sys.argv[1]), reviews(sys.argv[2])
definition = -(-len(Path(sys.argv[3]).read_text()) // 4)
assert real and bare and all(r - b >= definition for r, b in zip(real, bare)), (real, bare, definition)
' "$tmp/real.json" "$tmp/bare.json" "$SKILLS_DIR/../agents/varde-reviewer/claude.md" \
  || fail "dispatch cost lost the agents/varde-reviewer definition"
echo "Conditions, mentions, hand-offs, preamble gates, inline modes, and dispatches classified."

# Qualified modes choose the route named by the qualifier. Suggested and cited
# modes remain mentions and do not contribute inline route cost.
qualifier_pair="$tmp/qualifier-pair"
caller="$qualifier_pair/skills/varde-caller"
change="$qualifier_pair/skills/varde-change"
mkdir -p "$caller/references" "$change/references"
cat > "$caller/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Small change | `references/micro.md` |
| Named plan | `references/plan.md` |
| Cited modes | `references/mentions.md` |
EOF
cat > "$caller/references/micro.md" <<'EOF'
Run `varde-change` build and follow its micro-change route.
EOF
cat > "$caller/references/plan.md" <<'EOF'
Apply the update through `varde-change build` (named-plan route).
EOF
cat > "$caller/references/mentions.md" <<'EOF'
Suggest `varde-change build` for a similar change.
This option was passed in from `varde-change build`.
EOF
cat > "$change/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Build workflow | `references/build.md` |
| Small task implementation | `references/build-micro-change.md` |
| Named-plan route | `references/plan.md` |
EOF
printf 'Named workflow steps.\n' > "$change/references/build.md"
printf 'Small task steps.\n' > "$change/references/build-micro-change.md"
printf 'Named plan steps.\n' > "$change/references/plan.md"

python3 -B "$FLOW" --json "$caller" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
routes = {r["route"]: r for r in d["routes"]}
micro, plan, mentions = (routes[name] for name in
                         ["Small change", "Named plan", "Cited modes"])
checks = {
    "unquoted build selects the micro-change entry stem": micro["inline"] == [
        {"target": "varde-change build", "resolved": "varde-change: Small task implementation"}],
    "named-plan qualifier overrides the build entry stem": plan["inline"] == [
        {"target": "varde-change build", "resolved": "varde-change: Named-plan route"}],
    "suggested and cited modes are mentions": [
        e["kind"] for e in d["external"] if e["from"] == "references/mentions.md"
    ] == ["mention", "mention"],
    "mentions add no inline route or token cost": mentions["inline"] == []
        and mentions["main_max_tokens"] == mentions["max_tokens"],
}
bad = [name for name, ok in checks.items() if not ok]
assert not bad, (bad, json.dumps(d, indent=1))
' || fail "qualified inline mode classification"
echo "Route qualifiers resolve and suggested or cited modes stay mentions."

# Entry routing: a SKILL.md heading named "Entry routing" hands off both an
# inline mode and an internal pointer, rather than counting them inline/loaded.
entry_skill="$pair/skills/varde-entry"
mkdir -p "$entry_skill/references"
cat > "$entry_skill/SKILL.md" <<'EOF'
---
name: varde-entry
description: Fixture skill.
---
# Entry Fixture

## Entry routing

Explicit review requests hand off to `varde-other check`. See
`references/redirect.md` for the fallback.

| The request is | Read |
|---|---|
| Do it | `references/do.md` |
EOF
printf 'Fallback text.\n' > "$entry_skill/references/redirect.md"
printf 'Do steps.\n' > "$entry_skill/references/do.md"

python3 -B "$FLOW" --json "$entry_skill" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
route = d["routes"][0]
external = [x for x in d["external"] if x["target"] == "varde-other check"]
redirect = next(e for e in d["edges"] if e["to"] == "references/redirect.md")
checks = {
    "entry-routing inline mode is a hand-off": external and external[0]["kind"] == "handoff",
    "entry-routing internal pointer is a hand-off": redirect["kind"] == "handoff",
    "entry-routing target not resolved inline": route["inline"] == [],
    "entry-routing target listed as a hand-off": "varde-other check" in route["handoffs"],
    "entry-routing redirect excluded from files": "references/redirect.md" not in route["files"],
    "entry routing adds no tokens": route["main_max_tokens"] == route["max_tokens"]
        and route["main_min_tokens"] == route["min_tokens"],
}
bad = [k for k, ok in checks.items() if not ok]
assert not bad, (bad, json.dumps(d, indent=1))
' || fail "entry routing hand-off classification"
echo "Entry routing hands off instead of counting inline or loaded."

# Table hand-off: a reference's table row that hands off is a hand-off; a
# SKILL.md route row that matches a hand-off phrase is still its route's entry.
table_skill="$pair/skills/varde-table"
mkdir -p "$table_skill/references"
cat > "$table_skill/SKILL.md" <<'EOF'
---
name: varde-table
description: Fixture skill.
---
# Table Fixture

| The request is | Read |
|---|---|
| Resume planning with no feature named | `references/steps.md` |
EOF
cat > "$table_skill/references/steps.md" <<'EOF'
| The goal | Do |
|---|---|
| Is unsettled | Hand off to `varde-other check` |
| Is settled | Read `references/more.md` |
EOF
printf 'More steps.\n' > "$table_skill/references/more.md"

python3 -B "$FLOW" --json "$table_skill" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
route = d["routes"][0]
checks = {
    "table hand-off row is a hand-off": "varde-other check" in route["handoffs"]
        and route["inline"] == [],
    "table load row still loads": "references/more.md" in route["files"],
    "SKILL.md route row is the entry": route["entry"] == ["references/steps.md"],
}
bad = [k for k, ok in checks.items() if not ok]
assert not bad, (bad, json.dumps(d, indent=1))
' || fail "table hand-off classification"
echo "Table hand-off rows hand off; SKILL.md route rows stay entries."

# Structure: a.md and b.md load each other (a cycle); hub.md loads six leaves.
shape="$tmp/shape-fixture"
mkdir -p "$shape/references"
cat > "$shape/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Hub | `references/hub.md` |
| Pair | `references/a.md` |
EOF
{
  echo '# Hub'
  for leaf in 1 2 3 4 5 6; do
    echo "- Read \`references/leaf$leaf.md\`."
    printf 'Leaf.\n' > "$shape/references/leaf$leaf.md"
  done
  echo '- The file `references/a.md` is only mentioned.'
} > "$shape/references/hub.md"
printf 'Read `references/b.md`.\n' > "$shape/references/a.md"
printf 'Read `references/a.md` again.\n' > "$shape/references/b.md"
report="$(python3 -B "$FLOW" "$shape")" || fail "structure findings changed the exit code"
grep -qF 'cycle: references/a.md <-> references/b.md' <<<"$report" || fail "cycle missing: $report"
grep -qF 'fan-out: references/hub.md (6 links out, target < 6)' <<<"$report" \
  || fail "fan-out missing: $report"
grep -qF 'density:' <<<"$report" || fail "density missing: $report"
python3 -B "$FLOW" --json "$shape" | python3 -c '
import json, sys
s = json.load(sys.stdin)[0]["structure"]
want = {"mutual_links": 1, "max_links_out": 6, "max_links_out_file": "references/hub.md",
        "links": 8, "linking_files": 3, "average_links": 2.67}
assert all(s[k] == v for k, v in want.items()), s
' || fail "structure JSON"
python3 -B "$FLOW" --write "$shape" >/dev/null
for row in '| Measure | Value | Target | Status |' '| Mutual links | 1 | 0 | defect |' \
  '| Max links out of one file | 6 (references/hub.md) | < 6 | warning |' \
  '- cycle: references/a.md <-> references/b.md'; do
  grep -qF -- "$row" "$shape/FLOW.md" || fail "FLOW.md Structure lacks '$row': $(cat "$shape/FLOW.md")"
done
echo "Structure metrics, cycle, fan-out and density findings, and the FLOW.md table reported."

# Modules: build-one.md and build-two.md group into module "build", plan-one.md
# into module "plan"; build-one.md loads plan-one.md, the one cross-module edge.
mods="$tmp/module-fixture"
mkdir -p "$mods/references"
cat > "$mods/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Do the work | `references/build-one.md` |
EOF
cat > "$mods/references/build-one.md" <<'EOF'
# Build one

Read `references/build-two.md`.
Read `references/plan-one.md`.
EOF
printf 'Build two.\n' > "$mods/references/build-two.md"
printf 'Plan one.\n' > "$mods/references/plan-one.md"
python3 -B "$FLOW" --json "$mods" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
checks = {
    "cross-module edges counted": d["structure"]["cross_module_edges"] == 1,
}
assert all(checks.values()), (checks, d)
' || fail "module grouping JSON"
python3 -B "$FLOW" --write "$mods" >/dev/null
doc="$(cat "$mods/FLOW.md")"
grep -qF '### build' <<<"$doc" || fail "no build module section: $doc"
grep -qF '### plan' <<<"$doc" || fail "no plan module section: $doc"
build_at="$(grep -n '^### build$' <<<"$doc" | cut -d: -f1)"
plan_at="$(grep -n '^### plan$' <<<"$doc" | cut -d: -f1)"
routes_at="$(grep -n '^## Routes$' <<<"$doc" | cut -d: -f1)"
[ "$build_at" -lt "$routes_at" ] && [ "$plan_at" -lt "$routes_at" ] \
  || fail "module sections not before Routes: $doc"
overview="$(sed -n "1,$((build_at - 1))p" <<<"$doc")"
[ "$(grep -c -- '-->|"1"|' <<<"$overview")" -eq 1 ] \
  || fail "overview lacks exactly one aggregated build->plan edge: $overview"
echo "Module grouping: files grouped by prefix, overview first, one aggregated edge."

# Complexity: entry.md loads mid.md unconditionally (depth 2); mid.md loads two
# leaves conditionally, so cyclomatic = 2 + 1 and cognitive = (1 + 2) * 2 = 6.
cx="$tmp/complexity-fixture"
mkdir -p "$cx/references"
cat > "$cx/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Do the work | `references/entry.md` |
EOF
cat > "$cx/references/entry.md" <<'EOF'
# Entry

Read `references/mid.md`.
EOF
cat > "$cx/references/mid.md" <<'EOF'
# Mid

- **Case A:** if X, load `references/leaf-a.md`.
- **Case B:** if Y, load `references/leaf-b.md`.
EOF
printf 'Leaf A.\n' > "$cx/references/leaf-a.md"
printf 'Leaf B.\n' > "$cx/references/leaf-b.md"
python3 -B "$FLOW" --json "$cx" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
r = d["routes"][0]
assert (r["cyclomatic"], r["cognitive"]) == (3, 6), r
assert d["structure"]["diagram_edges"] == 4, d["structure"]
assert (d["structure"]["max_route_files"],
        d["structure"]["max_route_files_route"]) == (4, "Do the work"), d["structure"]
' || fail "complexity, diagram edges, or route-files formula"
python3 -B "$FLOW" "$cx" | grep -qF "Max route cyclomatic: 3" || fail "cyclomatic missing from report"
python3 -B "$FLOW" "$cx" | grep -qF "Max route cognitive: 6" || fail "cognitive missing from report"
python3 -B "$FLOW" "$cx" | grep -qF "Diagram edges: 4" || fail "diagram edges missing from report"
python3 -B "$FLOW" "$cx" | grep -qF "Most files reached by one route: 4 (Do the work)" \
  || fail "route-files missing from report"
echo "Flow complexity: cyclomatic, cognitive, diagram edges, and route-files" \
     "pinned against a hand-computed fixture."

# File kind: entry.md conditionally points to a marked reference r.md and to a
# procedure p.md; the edge into r.md is a lookup, not a branch. r.md's own
# conditional edge to leaf.md counts as entry's branch at entry's depth (no
# added nesting): cyclomatic = 2 branches + 1, cognitive = (1+1) + (1+1) = 4.
kind="$tmp/kind-fixture"
mkdir -p "$kind/references"
cat > "$kind/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Do the work | `references/entry.md` |
EOF
cat > "$kind/references/entry.md" <<'EOF'
# Entry

- **Case A:** if X, load `references/r.md`.
- **Case B:** if Y, load `references/p.md`.
EOF
cat > "$kind/references/r.md" <<'EOF'
<!-- kind: reference -->
# R

- **Case C:** if Z, load `references/leaf.md`.
EOF
printf 'Body of P.\n' > "$kind/references/p.md"
printf 'Leaf body.\n' > "$kind/references/leaf.md"
python3 -B "$FLOW" --json "$kind" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
r = d["routes"][0]
assert (r["cyclomatic"], r["cognitive"], r["lookups"]) == (3, 4, 1), r
assert d["references"] == ["references/r.md"], d["references"]
assert set(r["files"]) == {"references/entry.md", "references/r.md",
                           "references/p.md", "references/leaf.md"}, r
' || fail "file kind: lookups and reference-caller depth"
python3 -B "$FLOW" --write "$kind" >/dev/null
grep -qE '^\| Do the work \|.* \| 1 \| ' "$kind/FLOW.md" \
  || fail "FLOW.md lacks the Lookups column: $(cat "$kind/FLOW.md")"
echo "File kind: a marked reference's edge is a lookup, not a branch, and adds no nesting."

# Diagram folding: entry.md loads a chain of two marked references (r1 -> r2)
# and a procedure q.md; r2.md finally loads leaf.md. The module diagram must
# draw no node for either reference, must fold both (transitively) into
# entry's own node label, and must draw one edge straight from entry to leaf.
fold="$tmp/fold-fixture"
mkdir -p "$fold/references"
cat > "$fold/SKILL.md" <<'EOF'
| The request is | Read |
|---|---|
| Do the work | `references/entry.md` |
EOF
cat > "$fold/references/entry.md" <<'EOF'
# Entry

- **Case A:** if X, load `references/r1.md`.
- **Case B:** if Y, load `references/q.md`.
EOF
cat > "$fold/references/r1.md" <<'EOF'
<!-- kind: reference -->
# R1

Read `references/r2.md`.
EOF
cat > "$fold/references/r2.md" <<'EOF'
<!-- kind: reference -->
# R2

Read `references/leaf.md`.
EOF
printf 'Body of Q.\n' > "$fold/references/q.md"
printf 'Leaf body.\n' > "$fold/references/leaf.md"
python3 -B "$FLOW" --write "$fold" >/dev/null
doc="$(cat "$fold/FLOW.md")"
grep -qF '["references/r1.md' <<<"$doc" && fail "reference r1.md drawn as its own node: $doc"
grep -qF '["references/r2.md' <<<"$doc" && fail "reference r2.md drawn as its own node: $doc"
grep -qF '### r1' <<<"$doc" && fail "reference-only module r1 kept a section: $doc"
grep -qF '### r2' <<<"$doc" && fail "reference-only module r2 kept a section: $doc"
grep -qF '["r1 (' <<<"$doc" && fail "reference-only module r1 kept an overview node: $doc"
grep -qF 'ref: references/r1.md (~' <<<"$doc" || fail "entry's label lacks folded reference r1.md: $doc"
grep -qF 'ref: references/r2.md (~' <<<"$doc" || fail "entry's label lacks the transitively folded r2.md: $doc"
grep -qF 'n0 --> n1' <<<"$doc" || fail "no solid edge from entry straight to leaf (via the folded chain): $doc"
grep -qF 'n0 -.-> n2' <<<"$doc" || fail "no dotted edge from entry to q: $doc"
echo "Diagram folding: references fold into their caller's label, transitively, with an edge to the procedure they reach."

set +e
python3 "$FLOW" >/dev/null 2>&1
status=$?
set -e
[ "$status" -eq 2 ] || fail "no arguments exited $status, want 2"

# Exit 1 (real missing targets) is allowed here; a traceback or bad JSON is not.
python3 "$FLOW" --json "$SKILLS_DIR"/varde-*/ >"$tmp/all.json" 2>"$tmp/all.err" || true
if grep -q Traceback "$tmp/all.err"; then
  fail "crashed on shipped skills: $(cat "$tmp/all.err")"
fi
python3 -m json.tool "$tmp/all.json" >/dev/null || fail "invalid JSON on shipped skills"
echo "skill-flow.py completes on every shipped skill."

# Route-scoped skip: entry file A says "skip `references/g.md`"; A reaches
# p.md which points to g.md. Route A drops g.md; route B (entry B), also
# reaching p.md, keeps g.md.
skip_skill="$tmp/skip-fixture"
mkdir -p "$skip_skill/references"
cat > "$skip_skill/SKILL.md" <<'EOF'
---
name: skip-fixture
description: Fixture skill.
---
# Fixture

| The request is | Read |
|---|---|
| Route A | `references/a.md` |
| Route B | `references/b.md` |
EOF
printf 'Read `references/p.md` for steps. This route skips `references/g.md`.\n' \
  > "$skip_skill/references/a.md"
printf 'Read `references/p.md` for steps.\n' > "$skip_skill/references/b.md"
printf 'Read `references/g.md` for guidance.\n' > "$skip_skill/references/p.md"
printf 'Guidance text.\n' > "$skip_skill/references/g.md"

python3 -B "$FLOW" --json "$skip_skill" | python3 -c '
import json, sys
d = json.load(sys.stdin)[0]
by_route = {r["route"]: r for r in d["routes"]}
a, b = by_route["Route A"], by_route["Route B"]
assert "references/g.md" not in a["files"], a
assert "references/g.md" in b["files"], b
assert "references/p.md" in a["files"] and "references/p.md" in b["files"]
' || fail "route-scoped skip did not drop g.md from route A only"
echo "Route-scoped skip drops a target and its exclusive descendants from one route only."

# FLOW.md: --write creates it, --check passes, then fails once the skill changes.
python3 -B "$FLOW" --write "$skill" >/dev/null || true
grep -qF 'flowchart TD' "$skill/FLOW.md" || fail "--write produced no chart"
sed -i.bak '/gone.md/d' "$skill/references/build.md" && rm -f "$skill/references/build.md.bak"
python3 -B "$FLOW" --write "$skill" >/dev/null
python3 -B "$FLOW" --check "$skill" >/dev/null || fail "--check failed right after --write"
printf '\nSee `references/extra.md`.\n' >> "$skill/SKILL.md"
printf 'Extra.\n' > "$skill/references/extra.md"
set +e
python3 -B "$FLOW" --check "$skill" >/dev/null
status=$?
set -e
[ "$status" -eq 1 ] || fail "--check missed a stale FLOW.md (exit $status)"
echo "FLOW.md write and drift check work."

# Every shipped skill's committed FLOW.md matches its current references.
python3 -B "$FLOW" --check "$SKILLS_DIR"/varde-*/ \
  || fail "stale FLOW.md; run skill-flow.py --write on the listed skills"
echo "Shipped FLOW.md files are current."
