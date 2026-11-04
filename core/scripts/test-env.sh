#!/usr/bin/env bash
# Source this file before running tests to keep HOME-relative writes in the repo.

_VARDE_TEST_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
_VARDE_TEST_ORIGINAL_HOME="${HOME:?HOME must be set before sourcing test-env.sh}"
if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    if [ "$(uname -s)" = Darwin ]; then
        PLAYWRIGHT_BROWSERS_PATH="$_VARDE_TEST_ORIGINAL_HOME/Library/Caches/ms-playwright"
    else
        PLAYWRIGHT_BROWSERS_PATH="$_VARDE_TEST_ORIGINAL_HOME/.cache/ms-playwright"
    fi
    export PLAYWRIGHT_BROWSERS_PATH
fi
export VARDE_WEBKIT_REQUIRED=1
: "${UV_CACHE_DIR:=$_VARDE_TEST_ORIGINAL_HOME/.cache/uv}"
export UV_CACHE_DIR
: "${UV_PYTHON_INSTALL_DIR:=${XDG_DATA_HOME:-$_VARDE_TEST_ORIGINAL_HOME/.local/share}/uv/python}"
export UV_PYTHON_INSTALL_DIR

SCRATCH="$_VARDE_TEST_ENV_DIR/.scratch/test-home"
mkdir -p "$SCRATCH/home" "$SCRATCH/dotnet"
export SCRATCH
export HOME="$SCRATCH/home"
export DOTNET_CLI_HOME="$SCRATCH/dotnet"
export XDG_CONFIG_HOME="$SCRATCH/config"
export XDG_DATA_HOME="$SCRATCH/data"
export XDG_CACHE_HOME="$SCRATCH/cache"
export VARDE_CONFIG_DIR="$SCRATCH/config/varde"
export VARDE_TREE_SITTER_CACHE_DIR="$SCRATCH/cache/tree-sitter"
# Grammars cannot be downloaded offline: seed the scratch cache once from the
# main checkout's prefetched cache (or VARDE_TREE_SITTER_SEED_DIR).
_git_common="$(git -C "$_VARDE_TEST_ENV_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
_seed="${VARDE_TREE_SITTER_SEED_DIR:-${_git_common:+$(dirname "$_git_common")/.varde/tree-sitter-cache}}"
if ! compgen -G "$VARDE_TREE_SITTER_CACHE_DIR/tree-sitter-language-pack/v*/libs/*" >/dev/null && [ -n "$_seed" ] && [ -d "$_seed" ]; then
    mkdir -p "$VARDE_TREE_SITTER_CACHE_DIR"
    cp -R "$_seed/." "$VARDE_TREE_SITTER_CACHE_DIR/"
fi
# TMPDIR stays the caller's: the sandbox blocks git config/hook writes and long AF_UNIX paths under the repo.

unset _VARDE_TEST_ENV_DIR _VARDE_TEST_ORIGINAL_HOME _git_common _seed
