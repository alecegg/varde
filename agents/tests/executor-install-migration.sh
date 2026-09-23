#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-executor-install.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

for harness in claude codex opencode; do
  case "$harness" in
    claude) extension="md"; variant="claude.md" ;;
    codex) extension="toml"; variant="codex.toml" ;;
    opencode) extension="md"; variant="opencode.md" ;;
  esac

  managed="$TEST_ROOT/managed-$harness"
  mkdir -p "$managed"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$managed/build.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$managed" -m >/dev/null
  [ ! -e "$managed/build.$extension" ] || { echo "FAIL: stale managed Build survived for $harness" >&2; exit 1; }
  [ -f "$managed/executor.$extension" ] || { echo "FAIL: Executor missing for $harness" >&2; exit 1; }

  selected="$TEST_ROOT/selected-$harness"
  mkdir -p "$selected"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$selected/build.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$selected" -m -a plan >/dev/null
  [ -f "$selected/build.$extension" ] || {
    echo "FAIL: selected install removed Build for $harness" >&2
    exit 1
  }

  blocked="$TEST_ROOT/blocked-$harness"
  mkdir -p "$blocked"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$blocked/build.$extension"
  printf 'unowned executor\n' >"$blocked/executor.$extension"
  cp "$blocked/executor.$extension" "$blocked/executor.before"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$blocked" -m >/dev/null
  [ -f "$blocked/build.$extension" ] || {
    echo "FAIL: blocked migration removed Build for $harness" >&2
    exit 1
  }
  cmp "$blocked/executor.before" "$blocked/executor.$extension" || {
    echo "FAIL: blocked migration changed Executor for $harness" >&2
    exit 1
  }

  unmanaged="$TEST_ROOT/unmanaged-$harness"
  mkdir -p "$unmanaged"
  printf 'unmanaged build must remain\n' >"$unmanaged/build.$extension"
  cp "$unmanaged/build.$extension" "$unmanaged/before"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$unmanaged" -m >/dev/null
  cmp "$unmanaged/before" "$unmanaged/build.$extension" || {
    echo "FAIL: unmanaged Build changed for $harness" >&2
    exit 1
  }
done

echo "Executor install migration passed."
