#!/usr/bin/env bash
# Test `just repo-map-refresh` in temp git repos with a stub `varde`.
set -euo pipefail
command -v just >/dev/null || { echo "skip: just not installed"; exit 0; }
ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/repo-map-refresh.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/bin"
export PATH="$TMP/bin:$PATH"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@e GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@e
cat > "$TMP/bin/varde" <<'STUB'
#!/usr/bin/env bash
# Stub: `--help` lists --stale unless STUB_OLD; build writes a pack when STUB_STALE.
echo "$*" >> "$STUB_LOG"
if [ "${3:-}" = build ] && [ "${4:-}" = --help ]; then
    [ -n "${STUB_OLD:-}" ] || echo "  --stale"
    exit 0
fi
[ -z "${STUB_STALE:-}" ] || echo "pack $RANDOM" > docs/repo-map/README.md
STUB
chmod +x "$TMP/bin/varde"
export STUB_LOG="$TMP/log"

new_repo() {
    local d="$TMP/$1"
    git init -q "$d"
    mkdir -p "$d/docs/repo-map"
    echo old > "$d/docs/repo-map/README.md"
    git -C "$d" add -A && git -C "$d" commit -qm init
    echo "$d"
}
run() { just --justfile "$ROOT/justfile" --working-directory "$1" repo-map-refresh; }
count() { git -C "$1" rev-list --count HEAD; }
fail() { echo "FAIL: $*" >&2; exit 1; }

main=$(new_repo main)
STUB_STALE=1 run "$main" >/dev/null
[ "$(count "$main")" = 2 ] || fail "main did not commit refreshed packs"
git -C "$main" log -1 --format=%s | grep -qx "Refresh repo map packs" || fail "commit message"
[ -z "$(git -C "$main" status --porcelain)" ] || fail "tree dirty after refresh"

: > "$STUB_LOG"
run "$main" >/dev/null
[ "$(count "$main")" = 2 ] || fail "fresh packs made a commit"

old=$(new_repo old)
STUB_OLD=1 STUB_STALE=1 run "$old" | grep -q skipped || fail "old CLI did not skip"
[ "$(count "$old")" = 1 ] || fail "old CLI committed"

git -C "$main" worktree add -q "$TMP/wt" -b wt
STUB_STALE=1 run "$TMP/wt" | grep -q "linked worktree" || fail "worktree did not skip"
[ "$(count "$TMP/wt")" = 2 ] || fail "worktree committed"

nomap=$(new_repo nomap)
git -C "$nomap" rm -rq docs/repo-map && git -C "$nomap" commit -qm rm
run "$nomap" | grep -q "no docs/repo-map" || fail "missing map did not skip"
echo "ok"
