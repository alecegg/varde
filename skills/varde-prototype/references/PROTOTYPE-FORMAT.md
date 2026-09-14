# Frontend Prototype File Format

## Locations

Frontend Prototype files live at one of two locations depending on how the `/varde-prototype` skill was invoked:

- **Standalone invocation**: `memory-bank/working/prototypes/<slug>/`
- **Plan-invoked invocation**: `memory-bank/working/plans/<plan-id>/prototypes/<slug>/`

The `<slug>` is a short kebab-case identifier for the prototype agreed upon with the user.

## File naming

Mockup files follow a versioned naming scheme:

- `variant-<a|b|c...>.html` — (optional) the Round 1 variants, one per structurally distinct direction; present only when a variants round ran
- `v<N>.html` — the mockup file for round N, starting at `v1.html` (seeded from the winning variant when a variants round ran)
- `style.css` — (optional) shared stylesheet shared by all mockup versions
- `README.md` — points to the latest version as the canonical mockup

Each revision round increments `N` by 1. Previous versions are retained for reference. `variant-*.html` files are retained as-is (never renumbered) once `v1.html` is seeded from the winner.

## Structure rules

### variant-<a|b|c...>.html (optional, Round 1 only)

- Same structural rules as `v<N>.html` below — a complete, standalone full-page mockup, not an embedded fragment.
- Must include an identical switcher bar across all variant files in the round: a small fixed-position element (e.g. bottom-center) with a plain `<a href="variant-<x>.html">` link to each sibling variant. No JavaScript — real navigation between full standalone pages, so each variant is always viewed at true full-page fidelity, never scaled down or embedded.

### v<N>.html

- Must be a valid, self-contained HTML document (``<!DOCTYPE html>``, `<html>`, `<head>`, `<body>`).
- CSS may be embedded in a `<style>` tag or linked via `<link rel="stylesheet" href="style.css">` when a shared stylesheet exists.
- JavaScript may be included only for interactivity explicitly agreed upon with the user (e.g. animations, transitions, state changes). Static mockups must not include JavaScript.
- Use semantic HTML elements where appropriate (`<header>`, `<nav>`, `<main>`, `<section>`, `<footer>`).
- Do not include external dependencies (CDN links, web fonts, icon libraries) unless explicitly agreed upon.

### style.css (optional)

- Shared stylesheet that applies across all mockup versions.
- Should define consistent colors, typography, spacing, and layout primitives.
- Must not reference external resources.

### README.md

- Must exist after the first mockup round.
- Must point to the latest version file as the canonical mockup.
- May include a brief description of what the prototype demonstrates.

## Examples

```
memory-bank/working/prototypes/dashboard-redesign/
├── variant-a.html
├── variant-b.html
├── variant-c.html
├── v1.html
├── v2.html
├── style.css
└── README.md
```

```
memory-bank/working/plans/042-dashboard-feature/prototypes/user-settings/
├── v1.html
├── README.md
```

## Conventions

- Always report the file path to the user after writing or updating a mockup.
- When Artifact or mcp__visualize is available, serve as a preview enhancement alongside the file path, never as a replacement.
- The `README.md` canonical pointer is authoritative — agents reading prototype storage should use it to find the latest version without inspecting HTML file timestamps.
