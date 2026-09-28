#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"
"$script_dir/storage-fallbacks.sh" "$root" >/dev/null

fixture="$(mktemp -d "${TMPDIR:-/tmp}/storage-fallbacks.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/varde-example/references"
printf '%s\n' '# Fixture' > "$fixture/varde-example/SKILL.md"
printf '%s\n' 'The bundle at `memory-bank/knowledge/` is intentional.' \
  > "$fixture/varde-example/references/bundle.md"
"$script_dir/storage-fallbacks.sh" "$fixture" >/dev/null

printf '%s\n' 'If paths fails, else use `memory-bank/working`.' \
  >> "$fixture/varde-example/references/bundle.md"
if "$script_dir/storage-fallbacks.sh" "$fixture" > "$fixture/result" 2>&1; then
  echo 'FAIL: storage fallback guard missed injected fallback' >&2
  exit 1
fi
grep -Fq 'varde-example/references/bundle.md:2' "$fixture/result" || {
  cat "$fixture/result" >&2
  exit 1
}
printf '%s\n' 'When varde-workflow is unavailable, use memory-bank/working for plans.' \
  > "$fixture/varde-example/references/bundle.md"
if "$script_dir/storage-fallbacks.sh" "$fixture" > "$fixture/result" 2>&1; then
  echo 'FAIL: storage fallback guard missed unavailable wording' >&2
  exit 1
fi
grep -Fq 'varde-example/references/bundle.md:1' "$fixture/result" || {
  cat "$fixture/result" >&2
  exit 1
}
echo 'Storage fallback guard catches injected instructions and allows bundle paths.'
