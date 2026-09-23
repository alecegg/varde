#!/usr/bin/env bash
#
# Run output evaluations for eligible skills changed between two Git refs.
#
# Usage:
#   run-changed-output-evals.sh --base REF [options] [-- RUNNER_OPTIONS]
#
# Options:
#   --base REF         required comparison base
#   --head REF         comparison head (default: HEAD)
#   --repo DIR         Git repository (default: enclosing repository)
#   --skills-dir PATH  skills path relative to repository (default: skills)
#   --list-only        print selected skill paths without running evaluations
#
# A selected directory must contain both SKILL.md and evals/evals.json.
# Paths print in stable repository-relative order. Arguments after `--` pass
# through to run-output-evals.sh for every selected skill.

set -euo pipefail

die() { printf 'error: %s\n' "$1" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SKILLS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO=""
SKILLS_DIR="skills"
BASE=""
HEAD_REF="HEAD"
LIST_ONLY=0
RUNNER_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="${2:?--base needs a value}"; shift 2 ;;
    --head) HEAD_REF="${2:?--head needs a value}"; shift 2 ;;
    --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
    --skills-dir) SKILLS_DIR="${2:?--skills-dir needs a value}"; shift 2 ;;
    --list-only) LIST_ONLY=1; shift ;;
    --) shift; RUNNER_ARGS=("$@"); break ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$BASE" ]] || die "--base is required"
if [[ -z "$REPO" ]]; then
  REPO="$(git -C "$DEFAULT_SKILLS_DIR" rev-parse --show-toplevel 2>/dev/null)" || \
    die "script is not inside a Git repository; pass --repo"
fi
[[ -d "$REPO" ]] || die "repository not found: $REPO"
REPO="$(cd "$REPO" && pwd)"
[[ "$SKILLS_DIR" != /* ]] || die "--skills-dir must be repository-relative"
[[ -d "$REPO/$SKILLS_DIR" ]] || die "skills directory not found: $SKILLS_DIR"
git -C "$REPO" rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || \
  die "base ref is not a commit: $BASE"
git -C "$REPO" rev-parse --verify --quiet "$HEAD_REF^{commit}" >/dev/null || \
  die "head ref is not a commit: $HEAD_REF"

RUNNER="$SCRIPT_DIR/run-output-evals.sh"
[[ -x "$RUNNER" ]] || die "output evaluation runner is not executable: $RUNNER"

candidates="$(mktemp)"
selected="$(mktemp)"
trap 'rm -f "$candidates" "$selected"' EXIT

while IFS= read -r -d '' changed_path; do
  relative="${changed_path#"$SKILLS_DIR"/}"
  [[ "$relative" == */* ]] || continue
  skill_name="${relative%%/*}"
  skill_path="$SKILLS_DIR/$skill_name"
  if [[ -f "$REPO/$skill_path/SKILL.md" && \
        -f "$REPO/$skill_path/evals/evals.json" ]]; then
    printf '%s\n' "$skill_path" >> "$candidates"
  fi
done < <(git -C "$REPO" diff --name-only -z "$BASE" "$HEAD_REF" -- "$SKILLS_DIR")

sort -u "$candidates" > "$selected"

if [[ "$LIST_ONLY" -eq 1 ]]; then
  cat "$selected"
  exit 0
fi

while IFS= read -r skill_path; do
  [[ -n "$skill_path" ]] || continue
  "$RUNNER" "$REPO/$skill_path" "${RUNNER_ARGS[@]}"
done < "$selected"
