#!/usr/bin/env bash
set -euo pipefail
# Pin the OpenCode adapter generation so results never depend on the host.
export VARDE_AGENTS_OPENCODE_VERSION="${VARDE_AGENTS_OPENCODE_VERSION:-1.4.0}"
OPENCODE_VARIANT=opencode.md
[ "${VARDE_AGENTS_OPENCODE_VERSION%%.*}" -lt 2 ] || OPENCODE_VARIANT=opencode-v2.md

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/varde-executor-install.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

for harness in claude codex opencode; do
  case "$harness" in
    claude) extension="md"; variant="claude.md" ;;
    codex) extension="toml"; variant="codex.toml" ;;
    opencode) extension="md"; variant="$OPENCODE_VARIANT" ;;
  esac

  managed="$TEST_ROOT/managed-$harness"
  mkdir -p "$managed"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$managed/build.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$managed" -m >/dev/null
  [ ! -e "$managed/build.$extension" ] || { echo "FAIL: stale managed Build survived for $harness" >&2; exit 1; }
  [ -f "$managed/varde-executor.$extension" ] || { echo "FAIL: Executor missing for $harness" >&2; exit 1; }

  selected="$TEST_ROOT/selected-$harness"
  mkdir -p "$selected"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$selected/build.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$selected" -m -a varde-planner >/dev/null
  [ -f "$selected/build.$extension" ] || {
    echo "FAIL: selected install removed Build for $harness" >&2
    exit 1
  }

  blocked="$TEST_ROOT/blocked-$harness"
  mkdir -p "$blocked"
  printf 'old managed build\n<!-- varde-managed-agent -->\n' >"$blocked/build.$extension"
  printf 'unowned executor\n' >"$blocked/varde-executor.$extension"
  cp "$blocked/varde-executor.$extension" "$blocked/varde-executor.before"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$blocked" -m >/dev/null
  [ -f "$blocked/build.$extension" ] || {
    echo "FAIL: blocked migration removed Build for $harness" >&2
    exit 1
  }
  cmp "$blocked/varde-executor.before" "$blocked/varde-executor.$extension" || {
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

  mention_only="$TEST_ROOT/mention-only-$harness"
  mkdir -p "$mention_only"
  printf 'This custom agent discusses varde-managed-agent labels.\n' >"$mention_only/varde-planner.$extension"
  cp "$mention_only/varde-planner.$extension" "$mention_only/before"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$mention_only" -a varde-planner -m >/dev/null
  cmp "$mention_only/before" "$mention_only/varde-planner.$extension" || {
    echo "FAIL: marker mention replaced an unowned plan for $harness" >&2
    exit 1
  }

  # A default (-f) install writes the ownership marker without -m, so a
  # later -m run can recognize the file as varde-managed and update it.
  marker_check="$TEST_ROOT/marker-$harness"
  mkdir -p "$marker_check"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$marker_check" -a varde-planner -f >/dev/null
  grep -Fq "varde-managed-agent" "$marker_check/varde-planner.$extension" || {
    echo "FAIL: default install omitted ownership marker for $harness" >&2
    exit 1
  }
  printf 'stale edit\n' >>"$marker_check/varde-planner.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$marker_check" -a varde-planner -m >/dev/null
  grep -Fq "stale edit" "$marker_check/varde-planner.$extension" && {
    echo "FAIL: -m did not update a marker-owned file for $harness" >&2
    exit 1
  }
  grep -Fq "varde-managed-agent" "$marker_check/varde-planner.$extension" || {
    echo "FAIL: -m removed the ownership marker for $harness" >&2
    exit 1
  }

  link_target="$TEST_ROOT/link-target-$harness"
  printf 'external target\n<!-- varde-managed-agent -->\n' >"$link_target"
  link_dir="$TEST_ROOT/link-$harness"
  mkdir -p "$link_dir"
  ln -s "$link_target" "$link_dir/varde-planner.$extension"
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$link_dir" -a varde-planner -m >/dev/null
  [ -L "$link_dir/varde-planner.$extension" ] || { echo "FAIL: -m replaced symlink for $harness" >&2; exit 1; }
  [ "$(readlink "$link_dir/varde-planner.$extension")" = "$link_target" ] || { echo "FAIL: -m changed symlink for $harness" >&2; exit 1; }
  "$AGENTS_DIR/install.sh" -t "$harness" -d "$link_dir" -a varde-planner -f >/dev/null
  [ ! -L "$link_dir/varde-planner.$extension" ] || { echo "FAIL: -f left symlink for $harness" >&2; exit 1; }
  grep -Fq 'external target' "$link_target" || { echo "FAIL: -f changed link target for $harness" >&2; exit 1; }
done

echo "Executor install migration passed."
