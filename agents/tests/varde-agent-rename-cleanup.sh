#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-rename-cleanup.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

OLD_NAMES="explore plan review executor"

for harness in claude codex opencode; do
  case "$harness" in
    codex) ext="toml"; marker='# varde-managed-agent' ;;
    *) ext="md"; marker='<!-- varde-managed-agent -->' ;;
  esac
  for mode in -m -f; do
    dir="$TEST_ROOT/$harness$mode"
    mkdir -p "$dir"
    for old in $OLD_NAMES; do
      printf 'old managed %s\n%s\n' "$old" "$marker" >"$dir/$old.$ext"
    done
    # Unmarked user-owned files that share an old name must survive.
    printf 'mine\n' >"$dir/plan.$ext"
    printf 'mine\n' >"$dir/review.$ext"

    preview="$("$AGENTS_DIR/install.sh" -t "$harness" -d "$dir" "$mode" -n)"
    for old in explore executor; do
      printf '%s\n' "$preview" | grep -Fq "Would remove renamed managed $dir/$old.$ext" ||
        fail "$harness $mode preview omitted $old"
      [ -f "$dir/$old.$ext" ] || fail "$harness $mode dry run removed $old"
    done

    "$AGENTS_DIR/install.sh" -t "$harness" -d "$dir" "$mode" >/dev/null
    for old in explore executor; do
      [ ! -e "$dir/$old.$ext" ] || fail "$harness $mode kept managed $old"
    done
    for old in plan review; do
      [ "$(cat "$dir/$old.$ext")" = mine ] || fail "$harness $mode changed unmarked $old"
    done
    for new in varde-explorer varde-planner varde-reviewer varde-executor; do
      grep -Fq "varde-managed-agent" "$dir/$new.$ext" || fail "$harness $mode missing $new"
    done
  done

  # With the unmarked plan/review gone, managed ones are removed in -m mode.
  dir="$TEST_ROOT/$harness-managed-all"
  mkdir -p "$dir"
  for old in $OLD_NAMES; do printf 'x\n%s\n' "$marker" >"$dir/$old.$ext"; done
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$dir" -m >/dev/null
  for old in $OLD_NAMES; do
    [ ! -e "$dir/$old.$ext" ] || fail "$harness -m kept managed $old"
  done
done

echo "Agent rename cleanup tests passed."
