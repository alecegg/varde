#!/usr/bin/env bash
set -euo pipefail

# Report removed instructions that may carry a behavior or interface rule.
# Cut-list entries use this one-line format:
# - id: ... | rule: "<line>" | enforced-by: <test or exit code>
# A removal is covered by quoted rule text, a rule ID on the line, or an
# enforcing test or exit code named both on the removed line and an entry.

usage() {
  cat <<'EOF'
Usage: removed-normative-lines.sh [base] [--cut-list file]

With no arguments, run the built-in self-test in a temporary Git repository.
The base defaults to none, which scans the unstaged diff. Pass a commit to
compare that commit with the worktree.
EOF
}

fail() {
  printf 'removed-normative-lines.sh: %s\n' "$*" >&2
  exit 1
}

is_normative() {
  local line=$1
  [[ "$line" =~ (^|[^[:alnum:]_])(must|never|do[[:space:]]+not|stop)([^[:alnum:]_]|$) ]] ||
    [[ "$line" =~ (^|[^[:alnum:]_])exit[[:space:]]+[0-9]+([^[:digit:]]|$) ]] ||
    [[ "$line" =~ (^|[^[:alnum:]_])--[a-z] ]]
}

cut_list_covers() {
  local rule=$1
  local entry enforcement rule_id exit_code

  while IFS= read -r entry || [[ -n "$entry" ]]; do
    [[ "$entry" == *"rule:"* ]] || continue
    if [[ "$entry" == *"$rule"* ]]; then
      return 0
    fi

    if [[ "$rule" =~ (^|[^[:alnum:]_])rule:[[:space:]]*([[:alnum:]_-]+([.][[:alnum:]_-]+)*) ]]; then
      rule_id=${BASH_REMATCH[2]}
      if [[ "$entry" == *"$rule_id"* ]]; then
        return 0
      fi
    fi

    [[ "$entry" == *"enforced-by:"* ]] || continue
    enforcement=${entry#*enforced-by:}
    enforcement=${enforcement%%|*}
    enforcement=${enforcement#"${enforcement%%[![:space:]]*}"}
    enforcement=${enforcement%"${enforcement##*[![:space:]]}"}
    if [[ -n "$enforcement" && "$rule" == *"$enforcement"* ]]; then
      return 0
    fi

    if [[ "$rule" =~ (^|[^[:alnum:]_])exit[[:space:]]+([0-9]+)([^[:digit:]]|$) ]]; then
      exit_code=${BASH_REMATCH[2]}
      if [[ "$enforcement" =~ (^|[^[:alnum:]_])exit[[:space:]]+"?$exit_code"?([^[:digit:]]|$) ]]; then
        return 0
      fi
    fi
  done < "$cut_list"

  return 1
}

assert_contains() {
  local text=$1
  local expected=$2
  case "$text" in
    *"$expected"*) ;;
    *) fail "self-test did not find: $expected" ;;
  esac
}

assert_not_contains() {
  local text=$1
  local unexpected=$2
  case "$text" in
    *"$unexpected"*) fail "self-test found unexpected text: $unexpected" ;;
    *) ;;
  esac
}

run_self_test() {
  local script_dir script_path temp_dir repo base output cut_output cut_status unmatched count

  script_dir=$(cd "$(dirname "$0")" && pwd)
  script_path=$script_dir/$(basename "$0")
  temp_dir=$(mktemp -d "/tmp/removed-normative-lines.XXXXXX")
  trap "rm -rf '$temp_dir'" EXIT
  repo=$temp_dir/repo

  git init -q "$repo"
  git -C "$repo" config user.name "Removed normative lines test"
  git -C "$repo" config user.email "removed-normative-lines@example.invalid"
  mkdir -p "$repo/skills" "$repo/agents/templates"
  cat > "$repo/skills/change.md" <<'EOF'
You must follow the exact bound task.
Never continue after a denied start check.
Do not omit the independent review.
Stop when the review check has blockers.
On failure, exit 7.
Use --bound-task for a task scan.
Must run skills/tests/task-ownership.sh before returning.
Do not skip rule: gate-42.
The mustard-colored banner is descriptive.
Ordinary descriptive sentence.
EOF
  cat > "$repo/agents/capabilities.json" <<'EOF'
{
  "description": "must preserve the role"
}
EOF
  cat > "$repo/agents/templates/builder.md" <<'EOF'
Do not retry without checking the verdict.
EOF
  cat > "$repo/skills/file with space.md" <<'EOF'
-- a/source must keep this line.
EOF
  cat > "$repo/outside.md" <<'EOF'
Must not be included because this file is outside the scan scope.
EOF
  git -C "$repo" add skills/change.md "skills/file with space.md" agents/capabilities.json agents/templates/builder.md outside.md
  git -C "$repo" commit -qm "baseline fixture"
  base=$(git -C "$repo" rev-parse HEAD)

  cat > "$repo/skills/change.md" <<'EOF'
The mustard-colored banner is descriptive.
Ordinary descriptive sentence.
EOF
  cat > "$repo/agents/capabilities.json" <<'EOF'
{}
EOF
  : > "$repo/agents/templates/builder.md"
  : > "$repo/skills/file with space.md"
  : > "$repo/outside.md"

  output=$(cd "$repo" && bash "$script_path" "$base") || fail "self-test scan failed"
  count=$(printf '%s\n' "$output" | awk 'NF { count++ } END { print count + 0 }')
  [[ "$count" -eq 11 ]] || fail "self-test expected 11 removed normative lines, got $count"
  assert_contains "$output" "skills/change.md:1:You must follow the exact bound task."
  assert_contains "$output" "skills/change.md:8:Do not skip rule: gate-42."
  assert_contains "$output" "agents/capabilities.json:2:  \"description\": \"must preserve the role\""
  assert_contains "$output" "agents/templates/builder.md:1:Do not retry without checking the verdict."
  assert_contains "$output" "skills/file with space.md:1:-- a/source must keep this line."
  assert_not_contains "$output" "mustard"
  assert_not_contains "$output" "outside.md"

  cat > "$temp_dir/cut-list.md" <<'EOF'
- id: direct-rule | rule: "You must follow the exact bound task." | enforced-by: skills/tests/existing-check.sh
- id: exit-rule | rule: "exit behavior" | enforced-by: exit 7
- id: named-test | rule: "ownership check" | enforced-by: skills/tests/task-ownership.sh
- id: rule-id | rule: gate-42 | enforced-by: skills/tests/gate-check.sh
EOF
  if cut_output=$(cd "$repo" && bash "$script_path" "$base" --cut-list "$temp_dir/cut-list.md"); then
    cut_status=0
  else
    cut_status=$?
  fi
  [[ "$cut_status" -eq 1 ]] || fail "self-test expected unmatched lines to exit 1, got $cut_status"
  assert_contains "$cut_output" "Unmatched removed normative lines:"
  unmatched=$(printf '%s\n' "$cut_output" | sed -n '/^Unmatched removed normative lines:$/,$p')
  assert_contains "$unmatched" "Never continue after a denied start check."
  assert_contains "$unmatched" "Use --bound-task for a task scan."
  assert_not_contains "$unmatched" "You must follow the exact bound task."
  assert_not_contains "$unmatched" "On failure, exit 7."
  assert_not_contains "$unmatched" "skills/tests/task-ownership.sh"
  assert_not_contains "$unmatched" "Do not skip rule: gate-42."

  printf 'removed-normative-lines.sh self-test passed\n'
}

shopt -s nocasematch

if [[ "$#" -eq 0 ]]; then
  run_self_test
  exit 0
fi

base=none
cut_list=
if [[ "$1" != --cut-list && "$1" != --help && "$1" != -h ]]; then
  base=$1
  shift
fi
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --cut-list)
      [[ "$#" -ge 2 ]] || { usage; exit 2; }
      [[ -z "$cut_list" ]] || { usage; exit 2; }
      cut_list=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ -n "$cut_list" ]]; then
  trap 'exit 1' PIPE
else
  trap 'exit 0' PIPE
fi

if [[ -n "$cut_list" && ! -r "$cut_list" ]]; then
  printf 'removed-normative-lines.sh: cannot read cut list: %s\n' "$cut_list" >&2
  exit 2
fi

if ! repo_root=$(git rev-parse --show-toplevel 2>/dev/null); then
  printf 'removed-normative-lines.sh: run from inside a Git worktree\n' >&2
  exit 2
fi

diff_file=$(mktemp "/tmp/removed-normative-lines.diff.XXXXXX")
trap 'rm -f "$diff_file"' EXIT
if [[ "$base" == none ]]; then
  git -C "$repo_root" diff --no-ext-diff --no-renames --unified=0 -- \
    skills/ agents/capabilities.json agents/templates/ > "$diff_file"
else
  git -C "$repo_root" diff --no-ext-diff --no-renames --unified=0 "$base" -- \
    skills/ agents/capabilities.json agents/templates/ > "$diff_file"
fi

records=()
unmatched=()
unmatched_count=0
current_file=
old_line=0
in_hunk=0
while IFS= read -r diff_line || [[ -n "$diff_line" ]]; do
  if [[ "$diff_line" == 'diff --git '* ]]; then
    current_file=
    in_hunk=0
    continue
  fi
  if [[ "$in_hunk" -eq 0 && "$diff_line" == '--- '* ]]; then
    current_file=${diff_line#--- }
    current_file=$(printf '%s\n' "$current_file" | sed -e 's/^"//' -e 's/"$//' -e 's/\t$//')
    current_file=${current_file#a/}
    continue
  fi
  if [[ "$diff_line" =~ ^@@\ -([0-9]+)(,[0-9]+)?\ \+ ]]; then
    old_line=${BASH_REMATCH[1]}
    in_hunk=1
    continue
  fi
  case "$diff_line" in
    -*)
      rule=${diff_line#-}
      if [[ -n "$current_file" ]] && is_normative "$rule"; then
        record="$current_file:$old_line:$rule"
        records+=("$record")
        if [[ -n "$cut_list" ]] && ! cut_list_covers "$rule"; then
          unmatched+=("$record")
          unmatched_count=$((unmatched_count + 1))
        fi
      fi
      old_line=$((old_line + 1))
      ;;
    ' '*)
      old_line=$((old_line + 1))
      ;;
  esac
done < "$diff_file"

for record in "${records[@]}"; do
  if ! printf '%s\n' "$record"; then
    exit 0
  fi
done

if [[ "$unmatched_count" -gt 0 ]]; then
  if ! printf 'Unmatched removed normative lines:\n'; then
    exit 0
  fi
  for record in "${unmatched[@]}"; do
    if ! printf '  %s\n' "$record"; then
      exit 0
    fi
  done
  exit 1
fi
