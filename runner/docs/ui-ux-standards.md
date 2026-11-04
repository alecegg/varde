# Mobile web UI standards

Use this checklist for iOS-first mobile web reviews. Apple’s Human Interface
Guidelines are platform guidance; spacing, navigation, and state requirements
below are Varde project standards. Checklist numbers identify standards. The
walk's `baselineItem` values refer to the earlier UX baseline numbering.

## Checklist: layout and navigation

1. **Safe areas.** Keep fixed headers, footers, and primary controls clear of
   the status/sensor area and home-indicator area. Use `env(safe-area-inset-*)`
   with a fallback where the page uses `viewport-fit=cover`. Apple describes
   safe areas as regions not obscured by system or interface views ([Layout](https://developer.apple.com/design/human-interface-guidelines/layout)).

2. **Touch targets.** Make every touch control at least 44 × 44 CSS px and leave
   enough space to avoid adjacent accidental taps. This is the automated web
   proxy for Apple’s recommended 44 × 44 pt iOS target size ([Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)).

3. **Spacing.** Use the project spacing scale 4, 8, 12, 16, 24, or 32 px for
   layout gaps and padding; use at least 16 px between the viewport edge and
   primary content. This scale is a project convention, not an Apple rule.

4. **Keyboard and viewport.** Keep a focused input and its action above the
   keyboard; reposition fixed composers and overlays on `window.visualViewport`
   resize and scroll ([VisualViewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport),
   [Apple viewport guidance](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/UsingtheViewport/UsingtheViewport.html)).
   The walk uses Chromium iPhone emulation with a synthetic viewport shrink to
   check composer bounds, page scroll, textarea text size, geometry stability,
   and keyboard-close restoration. This checks application logic; no operating-
   system keyboard is shown and iOS Safari behavior is unverified. Playwright
   WebKit is required, and the walk fails if it cannot launch; WebKit also does
   not prove real iOS behavior.

5. **Navigation.** Use one primary navigation system per view. Keep the header
   title and action placement consistent; provide a clear, working Back action
   on pushed/detail views. Apple recommends standard, consistent Back and
   Close controls ([Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars), [Gestures](https://developer.apple.com/design/human-interface-guidelines/gestures)).
   Keep Back at the left on every page, use one shared pattern, and make its
   control symmetric with a centered arrow. Plan pages use the shared control.
   On mobile titled pages, put the app name and logo in the menu, not the header.

6. **Working controls.** Every visible button, link, and disclosure control
   performs its labeled action or is visibly disabled. Remove decorative
   controls that look actionable but have no result.

## Checklist: content and controls

7. **Useful banners.** Show a banner only when it communicates a current,
   relevant status or action. Give it a clear dismissal or resolution path;
   do not repeat information already evident in the page.

8. **Disabled and empty states.** Explain why an action or content is
   unavailable and give the user a direct enable, retry, or next-step path when
   one exists. Do not show an unexplained disabled control or blank state.

9. **Icons.** Use one coherent icon family, weight, and size. Give icon-only
   controls an accessible name and a visible or discoverable purpose.

10. **Inputs.** Give each input a persistent label or accessible name. Keep
    controls 44–48 px tall and within their parent width; textareas may grow to
    160 px, then scroll internally. Use at least 16 px text in mobile form
    controls to avoid Safari's reported focus auto-zoom behavior ([Safari input
    zoom](https://www.danburzo.ro/css-safari-zoom-inputs/));
    this threshold is a web convention, not an Apple HIG rule. Provide the
    appropriate input type and keyboard hint, as Apple recommends ([Text fields](https://developer.apple.com/design/human-interface-guidelines/text-fields)).

11. **Horizontal fit.** At a 390 px viewport, page content must not create
    horizontal scrolling. Long text, tables, and media must wrap, scale, or
    scroll within their own region.

12. **Appearance and contrast.** Review every route in light and dark
    appearance. Text contrast must be at least 4.5:1; controls and icons must
    remain distinguishable in both. The 4.5:1 minimum is WCAG 2.x success
    criterion 1.4.3 for normal-size text ([Contrast (Minimum)](https://www.w3.org/TR/WCAG22/#contrast-minimum)),
    not an Apple rule; Apple's guidance on appearances is
    [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode).

13. **Settings controls.** Keep checkboxes at normal control size. Do not put
    raw JSON, TOML, or text editors in settings; provide a real form with
    per-field help or omit the setting.
14. **Stable loading.** Data views use stable loading placeholders and do not
    pop in late, shift layout, or flash empty states before data arrives.
15. **Actionable connection status.** Do not show persistent Online,
    Retrying, or Connecting bubbles. Show connection problems only for a real,
    actionable failure, using a banner or toast.
16. **Popover defaults.** Plan comment popovers start closed and open only after
    a user action.
17. **Queue ordering.** Queue items can be reordered with a drag handle and
    move-up/move-down controls.

## Walk behavior

Run [`scripts/walk-mobile-ui.mjs`](../../workflow/src/varde_workflow/skills/varde-review-ui/scripts/walk-mobile-ui.mjs)
with an explicit target URL. The walk reports findings using the checklist
numbers above and saves light and dark screenshots for each discovered route.
It prevents native form submission and aborts non-GET HTTP requests (reported
as `blockedWrites`), and waits for SPA content before measuring.

UX approval is fail-closed. Follow the preflight, coverage, and verdict gate in
[`ux-advocate.md`](../../workflow/src/varde_workflow/skills/varde-review-ui/references/ux-advocate.md).
Preflight checks interaction with one click.

## Baseline detectors

The walk emits these stable `baselineItem` IDs:

- Baseline 7: Flag chat or agent rows ending in digits, duplicate role labels, and a
   roster row that summarizes multiple instances of one role.

- Baseline 8: Flag a bordered or colored settings container that contains two or more
   group headings.

- Baseline 9: Flag settings rows matching local, host, path, socket, debug, development,
   worktree, token-path, home-directory, or absolute-path patterns as
   `review: host/dev-specific`. This is a review candidate, not proof the
   setting should be removed.

- Baseline 10: Flag input height outside 44–48 px, textarea height above 160 px, or an
    input wider than its parent container.
- Baseline 11: Measure menu-icon bar length spread, gap spread, and center offset when
    separate bars are exposed in the DOM. A glyph-only menu icon gets one
    review finding because its bars cannot be measured independently.
- Baseline 13: Require exactly two app-icon choices on Settings > Appearance.
- Baseline 14: Flag health/status menu entries and require a status/health indicator in
    at least one visible header.

## Coverage and limits

The walk checks:

- touch targets, safe areas, and 16 px edge gutters
- input text size and horizontal overflow
- light/dark contrast
- navigation consistency and disabled-state explanations
- multiline composer growth and long pages

The Chromium run overrides safe-area insets to 44 px top and 34 px bottom.

Inspect screenshots for banner usefulness, icon consistency, explanation
quality, and ambiguous row grouping. iOS Simulator is optional and unavailable
on this host. Playwright WebKit with iPhone emulation is the required automated
keyboard and safe-area gate; it does not prove iOS Safari behavior. The
real-phone checkpoint below is the keyboard acceptance gate for iOS.

## Real-phone checkpoint

Run these checks on physical iPhone Safari and report each as pass, fail, or
untested under `REAL-DEVICE CHECKPOINT REQUIRED`:

1. Tap the composer: focus causes no page shift or zoom, and the composer stays
   above the keyboard.
2. Type several lines: the composer grows to about five lines, then scrolls
   internally without hiding its actions.
3. Dismiss the keyboard: the layout returns without a jump or gap, and the
   draft remains.
4. Rotate with the keyboard open and closed: composer and actions remain
   visible, with no clipped content.
5. Check notch and home-indicator gutters: headers, composer, and controls stay
   clear of both unsafe areas.
6. Tap the hamburger: the menu opens, its entries are reachable, and it can be
   dismissed.
7. Swipe horizontally on each main view: the page does not scroll sideways.
8. Enable dark mode: text, icons, and controls remain legible and distinct.
