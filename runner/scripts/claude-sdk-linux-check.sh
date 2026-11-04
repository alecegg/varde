#!/usr/bin/env bash
set -euo pipefail

script_dir="$( (cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) )"
repo_root="$(git -C "${script_dir}/../.." rev-parse --show-toplevel)"
image="${VARDE_CLAUDE_SDK_LINUX_IMAGE:-docker.io/library/node:22-bookworm}"

podman run --rm --pull=missing \
  --volume "${repo_root}:/workspace:Z" \
  --workdir /workspace \
  "${image}" \
  bash -euc '
    curl -LsSf https://astral.sh/uv/0.12.19/install.sh \
      | env UV_VERSION=0.12.19 sh
    export PATH="/root/.local/bin:${PATH}"
    export UV_PROJECT_ENVIRONMENT=/tmp/varde-claude-sdk-venv
    uv --version | grep -q "^uv 0.12.19 "
    node --version
    npm test --prefix runner/node-host/engines/claude-sdk
    uv run --locked --all-packages --group dev \
      pytest runner/tests/test_claude_sdk_parity.py -q -rs
  '
