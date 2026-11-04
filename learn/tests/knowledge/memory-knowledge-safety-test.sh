#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../../../core/tests/lib/repo.sh"
ROOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/varde-memory-safety.XXXXXX")"
ROOT_DIR="$(cd "$ROOT_DIR" && pwd -P)"
trap 'rm -rf "$ROOT_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Print every knowledge/config file matching a secret or machine-specific
# path. Exit status is grep's: 0 when a match was found.
scan_knowledge() {
  find "$ROOT_DIR" \( -path '*/memory-bank/knowledge/*' \
    -o -path '*/memory-bank/config/*' \
    -o -path '*/memory-bank/README.md' \) -type f \
    -exec grep -EIH \
    '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|/Users/[^/[:space:]]+|/home/[^/[:space:]]+|file://)' {} +
}

mkdir -p "$ROOT_DIR/memory-bank/knowledge/reference" "$ROOT_DIR/memory-bank/config"
cp "$REPO_ROOT/.gitignore" "$ROOT_DIR/.gitignore"
git -C "$ROOT_DIR" init -q
printf 'safe fixture\n' >"$ROOT_DIR/memory-bank/knowledge/reference/example.md"
if ! find "$ROOT_DIR/memory-bank" -type f | grep -q .; then
  fail "no knowledge files were created to scan"
fi

# A clean knowledge tree must pass.
if scan_knowledge; then
  fail "clean knowledge was flagged as unsafe"
fi

# Seed violations so the scan is proven able to fail; remove each seed and the
# clean check must pass again.
leak="$ROOT_DIR/memory-bank/knowledge/reference/leaked.md"
printf 'See /Users/example/notes.md\n' >"$leak"
scan_knowledge >/dev/null || fail "scan missed a seeded machine-specific path"
printf 'api_key = "sk-abcdefghijklmnopqrstuvwx"\n' >"$leak"
scan_knowledge >/dev/null || fail "scan missed a seeded api key"
printf '%s\n' 'ghp_abcdefghijklmnopqrstuvwxyz0123456789' >"$leak"
scan_knowledge >/dev/null || fail "scan missed a seeded github token"
rm "$leak"
if scan_knowledge; then
  fail "removed seed was still flagged"
fi

echo "memory knowledge safety tests passed"
