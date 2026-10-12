#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
tmp_root=$(mktemp -d)
trap 'rm -rf "$tmp_root"' EXIT HUP INT TERM
export TMPDIR="$tmp_root"

cargo test --manifest-path "$repo_root/clis/Cargo.toml" -p varde-toz-core

leaks=$(find "$TMPDIR" -mindepth 1 \( \
    -name 'toz-test-*' -o \
    -name 'toz-search-*' -o \
    -name 'toz-migration-*' \
  \) -print)
if [ -n "$leaks" ]; then
  printf 'temporary test directories remain:\n%s\n' "$leaks" >&2
  exit 1
fi
