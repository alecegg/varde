#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/core/scripts/test-env.sh"

python_playwright="$(uv run --locked --all-packages --group dev python -c 'from importlib.metadata import version; print(version("playwright"))')"
node_playwright="$(node -p "require('$ROOT/runner/ui/node_modules/playwright/package.json').version")"
if [ "$python_playwright" != "$node_playwright" ]; then
    echo "Python Playwright ($python_playwright) and Node Playwright ($node_playwright) must match to share the WebKit revision." >&2
    exit 1
fi

uv run --locked --all-packages --group dev playwright install webkit

uv run --locked --all-packages --group dev python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.webkit.launch()
    browser.close()
print("PASS Python Playwright WebKit launch")
PY

node --input-type=module - "$ROOT" <<'JS'
const { webkit } = await import(`${process.argv[2]}/runner/ui/node_modules/playwright/index.mjs`);

const browser = await webkit.launch();
await browser.close();
console.log('PASS Node Playwright WebKit launch');
JS
