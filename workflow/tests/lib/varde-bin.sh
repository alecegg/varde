#!/usr/bin/env bash
# Select the varde built in this checkout instead of a globally installed one.
# `VARDE_BIN` overrides the checkout binary when a test needs its own wrapper.

checkout_varde() {
  local repo_root="$1"
  local bin="${VARDE_BIN:-$repo_root/.venv/bin/varde}"
  if [ -x "$bin" ]; then
    printf '%s\n' "$bin"
    return 0
  fi
  command -v varde || true
}

prefer_checkout_varde() {
  local repo_root="$1"
  local bin
  bin="$(checkout_varde "$repo_root")"
  if [ -z "$bin" ]; then
    printf 'note: no varde binary found for %s or on PATH\n' "$repo_root" >&2
    return 0
  fi
  PATH="$(cd "$(dirname "$bin")" && pwd):$PATH"
  export PATH
}
