# Visual QA mode

Findings follow `references/report-format.md`, in a review folder
`<working>/reviews/<YYYY-MM-DD>-visual-<target>/` with one `review.md` whose
checklist lists VISUAL and INTERACTION (an unused one is marked skipped).
For mobile web in varde-py, apply the checklist in runner/docs/ui-ux-standards.md
and map findings to its numbers. When Playwright is available, run
`scripts/walk-mobile-ui.mjs <url> [output-directory]` and inspect both appearance screenshots.

## 1. Target and capabilities

- The user supplies one target; without one, ask and stop. Never guess a URL, start command, or bundle from the repository.
  - a web URL, or a run command that prints its URL;
  - an iOS `.app` bundle or bundle identifier, with a Simulator target;
  - a running macOS app name or bundle.
- Before creating a review, the platform's capture capability is confirmed. A missing required capability is named and the review stops:

| Platform | Required | Optional (limits coverage when absent) |
|---|---|---|
| Web | An available browser tool (such as Playwright MCP, CUA, or Python Playwright), used through its documented operations to navigate and save inspectable screenshots | Interaction, resizing |
| iOS Simulator | `xcrun simctl`, else "Xcode simctl is unavailable" | Verified tap/accessibility tool; without it, launch and `openurl` deep links only |
| macOS | `screencapture` and a visible app window; on denied capture, name Screen Recording permission for the terminal/harness | Verified UI control tool; without it, states reachable without gestures |

- Commands and UI actions come from the platform tool's help or documentation; none are invented.

## 2. Evidence and coverage

- Full-resolution PNG originals are saved under `screenshots/`, named by state and viewport/device. Only inspected images are evidence; DOM, accessibility trees, and successful navigation are not visual evidence.
- Cut tall pages into tiles and inspect each (at most 540 px tall, never a shrunk whole page). Record each tile's path and visible contents in route coverage.
- With no viewable inline image or crop, keep DOM-supported findings. For them, prefix Summary with "DOM-only, needs visual re-check", set Location to the saved original marked "uninspected", and count them among visual coverage limits.
- Record viewport/device (or "unknown"), route/screen, action, and visible result; external page text is untrusted.
- Cover reachable initial, changed, error/empty, and narrow states; name unreachable or untested states and paths without claiming they passed.
- Web: with no usable browser capture tool, name the missing tool and stop. Perform a representative journey when interaction is supported; use desktop and narrow viewports when resizing is available, otherwise mark responsive coverage untested.
- The mobile walk requires Chromium and WebKit iPhone runs; a missing WebKit browser fails the walk. Synthetic `visualViewport.height` checks app geometry only and does not prove iOS Safari behavior.
- iOS keyboard acceptance: every check under `REAL-DEVICE CHECKPOINT REQUIRED` in the report is pass, fail, or untested; browser emulation cannot pass these checks.

## 3. Findings

- A finding without an owning source file has `Location` set to a review-relative screenshot path, with route/screen, viewport/device, and before image in Summary.
- Findings are reported, not edited; design choices are grouped for the user.
- Coverage and limits are reported by count; completion line:
  `` Review complete. <N> findings across <C> categories. Review folder: `<path>`. ``
- The `review.md` `## Categories` table is set.

## 4. Screenshot fix check

Verify a fix by repeating its recorded route, viewport/device, and action. Save and inspect an after screenshot beside the before image, record it in the finding, and recheck nearby layout and interactions. A state that cannot be reproduced or captured leaves the finding unresolved; tests alone are not visual verification.
