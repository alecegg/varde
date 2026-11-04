---
topic: varde-review-ui/platform-steps
version: 1
summary: iOS Simulator and macOS app capture procedure for visual QA
---

## Platform steps

- Review folder: create `<working>/reviews/<YYYY-MM-DD>-visual-<target>/` with one `review.md` whose checklist lists VISUAL and INTERACTION (mark an unused one skipped). Save full-resolution PNG originals under `screenshots/`, named by state and viewport/device.
- iOS Simulator: launch the supplied app on the selected Simulator target and capture the screens needed for coverage. Do not invent tap or typing commands.
- macOS app: capture the visible app window with the available screenshot tool. If capture is unavailable, name the missing tool or permission and stop.
- macOS app, no numeric window ID: select the named app window interactively with `screencapture -i -w` (the app name is not a window ID). If no user is present to select it, ask for a window ID.
- Findings without an owning source file: set `Location` to a review-relative screenshot path; put route/screen, viewport/device, and before image in Summary.
- Verifying a screenshot fix: repeat the recorded route, viewport/device and action. Save and inspect an after screenshot beside the before image, record it in the finding, and recheck nearby layout and interactions.
