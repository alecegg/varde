#!/usr/bin/env bash
set -euo pipefail

script_dir="$( (cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) )"
repo_root="$(git -C "${script_dir}/../.." rev-parse --show-toplevel)"
image="${VARDE_PI_DURABLE_LINUX_IMAGE:-docker.io/library/node:22-bookworm}"

podman run --rm --pull=missing \
  --volume "${repo_root}:/workspace:Z" \
  --workdir /workspace \
  "${image}" \
  bash -euc '
    curl -LsSf https://astral.sh/uv/0.12.19/install.sh \
      | env UV_VERSION=0.12.19 sh
    export PATH="/root/.local/bin:${PATH}"
    export UV_PROJECT_ENVIRONMENT=/tmp/varde-pi-durable-venv
    uv --version | grep -q "^uv 0.12.19 "
    node --version
    rm -rf /tmp/pi-durable-package /tmp/varde-pi-durable-state
    mkdir -p /tmp/pi-durable-package
    cp -R runner/node-host/. /tmp/pi-durable-package/
    npm ci --prefix /tmp/pi-durable-package/engines/durable --ignore-scripts
    export VARDE_PI_DURABLE_ENGINE_PATH=/tmp/pi-durable-package/engines/durable/index.mjs
    export VARDE_RUNNER_STATE_DIR=/tmp/varde-pi-durable-state
    uv run --locked --all-packages --group dev \
      pytest runner/tests/test_pi_durable_e2e.py -q -rs
    node --test /tmp/pi-durable-package/engines/durable/test/*.test.mjs
  '
