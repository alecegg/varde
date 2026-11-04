#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
podman_bin="${PODMAN:-podman}"

if ! command -v "$podman_bin" >/dev/null 2>&1; then
  echo "Podman is required for the Linux Node host check" >&2
  exit 1
fi

"$podman_bin" run --rm \
  --user node \
  --volume "$repo_root:/input:ro" \
  --workdir /tmp \
  node:22 \
  sh -ec '
    mkdir /tmp/varde-source
    cp -a /input/. /tmp/varde-source/
    cd /tmp/varde-source
    if ! command -v curl >/dev/null 2>&1; then
      echo "node:22 image must provide curl to install uv" >&2
      exit 1
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    required_uv=$(sed -n "s/^required-version = \"==\([^\"]*\)\"/\1/p" pyproject.toml)
    if [ -z "$required_uv" ]; then
      echo "could not read the workspace uv version pin" >&2
      exit 1
    fi
    uv self update "$required_uv"
    uv run --python 3.14 --group dev pytest runner/tests/test_node_host_config.py runner/tests/node_host -q
    npm ci --ignore-scripts --prefix runner/node-host
    npm ci --ignore-scripts --prefix runner/node-host/engines/fake
    npm test --prefix runner/node-host
  '
