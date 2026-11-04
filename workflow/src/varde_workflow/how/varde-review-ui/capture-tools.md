---
topic: varde-review-ui/capture-tools
version: 1
summary: Web screenshot capture, image inspection fallbacks, preview and design-check commands for visual QA
---

## Capture and inspect tools

- Prefer inline Playwright screenshots. If Read cannot display an original, inspect single-region native-resolution tiles or crops, made with Playwright (clip or element capture) or with `sips -c` on macOS. Cut tiles at most 540 px tall (measured with Sonnet 5.5: 390x844 fails; 390x422 and 358x543 work).
- Run the supplied command and use its URL; if none is reported, ask the user.
- For an HTML or CSS file, when `varde design --help` succeeds, run `varde design check --json <path>` first and list its findings; it does not replace screenshots.
- If Playwright MCP cannot start, use Python Playwright to capture and save original PNGs.
- For mobile web in varde-py, when Playwright is available, run `scripts/walk-mobile-ui.mjs <url> [output-directory]`.
- [`scripts/shot.sh`](../scripts/shot.sh) (`shot.sh URL OUT.jpg [WIDTH] [HEIGHT]`) makes a lossy JPEG preview; save the PNG original separately.
- iOS Simulator is optional and unavailable on this host.
- For iOS keyboard acceptance, run the `Real-phone checkpoint` in runner/docs/ui-ux-standards.md on physical iPhone Safari.
