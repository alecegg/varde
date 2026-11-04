# WebKit testing

The test environment shares one Playwright browser cache between Python and
Node. `core/scripts/test-env.sh` sets `PLAYWRIGHT_BROWSERS_PATH` to
`~/Library/Caches/ms-playwright` on macOS (or `~/.cache/ms-playwright` on
Linux) and marks WebKit as required. `just test` and `just test-baseline`
install and launch-check the WebKit revisions pinned by both the Python and
Node Playwright lockfiles. A browser install or launch error fails setup.

To install and verify both engines from the repository root:

```sh
bash runner/scripts/install-webkit-browsers.sh
```

The runner UI smoke test launches Playwright WebKit with the iPhone 15 device
descriptor, opens a local HTML file, shrinks a synthetic `visualViewport`, and
asserts that a fixed composer moves above the reduced viewport:

```sh
source core/scripts/test-env.sh
bash runner/scripts/install-webkit-browsers.sh
npm run test:webkit-viewport --prefix runner/ui
```

Or run `just test-webkit` from the repository root. It installs UI dependencies,
installs WebKit with Python Playwright, launch-checks both Python and Node
Playwright, and runs the viewport smoke test.

WebKit and Chromium are separate engines. This checks app layout behavior
against a WebKit page with a synthetic viewport change; it does not emulate the
iOS keyboard or verify Safari's real keyboard animation and safe-area behavior.

The ux-advocate mobile walk launches both Chromium and WebKit. Run it from the
repository root with Node Playwright resolvable from the workflow script:

```sh
export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright"
export NODE_PATH="$PWD/runner/ui/node_modules"
bash runner/scripts/install-webkit-browsers.sh
node workflow/src/varde_workflow/skills/varde-review-ui/scripts/walk-mobile-ui.mjs \
  "$URL" mobile-ui-walk
```

The repository pins Node Playwright to the same version as Python Playwright,
so the helper-installed WebKit revision works for either runtime. The helper
installs the browser and fails if either Python or Node cannot launch it.
