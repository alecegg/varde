#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CORE_SKILLS=(
  varde-agent-doc-authoring
  varde-change
  varde-docs
  varde-explore
  varde-knowledge
  varde-prototype
  varde-review
)

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_text() {
  local file="$1"
  local text="$2"
  grep -F "$text" "$file" >/dev/null || fail "$file lacks: $text"
}

# Each skill routes to exactly these reference files from its SKILL.md, and each
# named file exists. This is the 15-mode manifest: 5 change, 4 review, 2 docs,
# 2 explore, 2 knowledge.
MODES_varde_change="status plan build verify orchestrate"
MODES_varde_review="report fix simplify scan"
MODES_varde_docs="refresh spec"
MODES_varde_explore="explain"
MODES_varde_knowledge="note reflect"

# A mode short enough that a reference file would be a hop to nothing lives in
# SKILL.md as a `## <Title>` section instead. It is still a mode — it must be
# present and must not also have a reference file shadowing it. See the two
# SKILL.md shapes in README.md.
INLINE_varde_explore="Explore"

check_modes() {
  local skill="$1" expected="$2" inline="${3:-}" total=0
  local manifest="$SKILLS_DIR/$skill/SKILL.md"
  for mode in $expected; do
    require_text "$manifest" "\`references/$mode.md\`"
    test -f "$SKILLS_DIR/$skill/references/$mode.md" ||
      fail "$skill routes to a missing references/$mode.md"
    total=$((total + 1))
  done
  for mode in $inline; do
    require_text "$manifest" "## $mode"
    local lower
    lower="$(printf '%s' "$mode" | tr 'A-Z' 'a-z')"
    test ! -f "$SKILLS_DIR/$skill/references/$lower.md" ||
      fail "$skill keeps $mode inline but references/$lower.md also exists"
  done
  # No extra routing rows: count the distinct references/<x>.md targets named in
  # the routing table, and require they match the manifest exactly. The table is
  # every line starting with `|`; each skill words its own column header.
  local found
  found="$(grep '^|' "$manifest" |
    grep -o '`references/[a-z0-9-]*\.md`' | sort -u | wc -l | tr -d ' ')"
  [ "$found" = "$total" ] ||
    fail "$skill routes to $found references, expected $total"
}

check_flat_layout() {
  local deep dirs manifest
  local skill_roots=()
  for manifest in "$SKILLS_DIR"/varde-*/SKILL.md; do
    skill_roots+=("${manifest%/SKILL.md}")
  done

  deep="$(find "${skill_roots[@]}" -mindepth 3 -type f |
    grep -v '/\(references\|scripts\|assets\|evals\)/[^/]*$' || true)"
  [ -z "$deep" ] || fail "content nested below one reference level: $deep"

  # Directories too, not just files. An emptied-out `references/modes/...` tree
  # survives a files-only check while still being the layout a reader sees.
  dirs="$(find "${skill_roots[@]}" -mindepth 2 -type d || true)"
  [ -z "$dirs" ] || fail "directory nested below the reference level: $dirs"

  dirs="$(find "${skill_roots[@]}" -mindepth 1 -maxdepth 1 -type d |
    grep -vE '/(references|scripts|assets|evals)$' || true)"
  [ -z "$dirs" ] || fail "unexpected top-level directory in a skill: $dirs"

  local skill manifests
  for skill in "${CORE_SKILLS[@]}"; do
    test -f "$SKILLS_DIR/$skill/SKILL.md" ||
      fail "core skill manifest missing: $skill"
  done
  manifests="${#CORE_SKILLS[@]}"
  [ "$manifests" = 7 ] || fail "expected 7 core skill manifests, found $manifests"
}

check_no_vendoring() {
  for path in _shared sync-shared-refs.sh sync-worktree-guidance.sh \
    sync-code-cli-guidance.sh; do
    test ! -e "$SKILLS_DIR/$path" || fail "retired vendoring artifact remains: $path"
  done
}

check_no_user_facing_flags() {
  # A routing table tells the agent which situation it is in. It must never
  # present key=value syntax, which reads as something a user should type.
  local hits
  hits="$(for manifest in "$SKILLS_DIR"/varde-*/SKILL.md; do
    grep -n '^|' "$manifest" | grep '[a-z_]=' | sed "s#^#$manifest:#" || true
  done)"
  [ -z "$hits" ] || fail "routing table presents an invocation flag: $hits"
}

check_invariants() {
  require_text "$SKILLS_DIR/varde-change/SKILL.md" "Verification reports never mutate plan files."
  require_text "$SKILLS_DIR/varde-change/SKILL.md" "Handoffs require a stopping boundary."
  require_text "$SKILLS_DIR/varde-change/SKILL.md" "Derive status from existing artifacts."
  require_text "$SKILLS_DIR/varde-review/SKILL.md" "Report mode never changes source files."
  require_text "$SKILLS_DIR/varde-review/SKILL.md" "Mutation requires fix or simplify mode."
  require_text "$SKILLS_DIR/varde-knowledge/SKILL.md" "Handoffs require a stopping boundary."
  require_text "$SKILLS_DIR/varde-explore/SKILL.md" "Do not create a plan or production code unless the user asks."
}

check_mapping() {
  local count duplicates retired
  count="$(wc -l < "$SCRIPT_DIR/workflow-map.tsv" | tr -d ' ')"
  [ "$count" = 21 ] || fail "expected 21 workflow mappings, found $count"
  duplicates="$(cut -f1 "$SCRIPT_DIR/workflow-map.tsv" | sort | uniq -d)"
  [ -z "$duplicates" ] || fail "duplicate workflow mappings: $duplicates"

  while IFS=$'\t' read -r source owner mode; do
    [ -n "$source" ] && [ -n "$owner" ] && [ -n "$mode" ] ||
      fail "incomplete workflow mapping"
    if [ "$owner" != internal ]; then
      test -f "$SKILLS_DIR/$owner/SKILL.md" || fail "missing owner $owner"
      grep -Fi "$mode" "$SKILLS_DIR/$owner/SKILL.md" >/dev/null ||
        fail "$source mode $mode missing from $owner"
    fi
  done < "$SCRIPT_DIR/workflow-map.tsv"

  # Every retired mode is gone as a mode and as a dedicated reference file.
  for gone in conclude friction distill handoff rule triage; do
    if ls "$SKILLS_DIR"/varde-*/references/"$gone".md >/dev/null 2>&1; then
      fail "retired mode $gone still has a dedicated reference file"
    fi
  done

  retired="$(rg -n 'varde-(dashboard|explain|plan|build|orchestrate|review-fix|simplify|spec|reflect|friction-distillation|friction|handoff|worktree|code-codebase-navigation|code-rule-authoring|code-rule-scan-triage)' \
    "$SKILLS_DIR"/varde-{explore,change,review,docs,knowledge,prototype,agent-doc-authoring} \
    --glob '*.md' || true)"
  retired="$(printf '%s\n' "$retired" | grep -vE '\.varde-spec-probe|varde-spec:generated:(start|end)' || true)"
  [ -z "$retired" ] || fail "active references contain retired skill names: $retired"
}

case "${1:-all}" in
  explore) check_modes varde-explore "$MODES_varde_explore" "$INLINE_varde_explore" ;;
  change) check_modes varde-change "$MODES_varde_change" ;;
  review) check_modes varde-review "$MODES_varde_review" ;;
  docs-knowledge)
    check_modes varde-docs "$MODES_varde_docs"
    check_modes varde-knowledge "$MODES_varde_knowledge"
    ;;
  all)
    check_modes varde-explore "$MODES_varde_explore" "$INLINE_varde_explore"
    check_modes varde-change "$MODES_varde_change"
    check_modes varde-review "$MODES_varde_review"
    check_modes varde-docs "$MODES_varde_docs"
    check_modes varde-knowledge "$MODES_varde_knowledge"
    check_flat_layout
    check_no_vendoring
    check_no_user_facing_flags
    check_invariants
    check_mapping
    ;;
  *)
    echo "Usage: $(basename "$0") [explore|change|review|docs-knowledge|all]" >&2
    exit 1
    ;;
esac
