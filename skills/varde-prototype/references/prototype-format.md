# Frontend Prototype File Format

## Locations

- **Standalone invocation**: `<working>/prototypes/<slug>/`
- **Plan-invoked invocation**: `<working>/plans/<plan-id>/prototypes/<slug>/`

`<slug>` is a short kebab-case identifier agreed with the user.

## Files

| File | Rules |
|---|---|
| `variant-<a\|b\|c...>.html` | Round 1 only, one per structurally distinct direction, present only when a variants round ran. Same rules as `v<N>.html`, plus a switcher bar in every variant: a small fixed element with plain `<a href="variant-<x>.html">` links to its siblings, so each variant opens as its own full page. |
| `v<N>.html` | The mockup for round N, starting at `v1.html` — seeded from the winning variant when a variants round ran. Each revision round increments `N`. |
| `style.css` | Optional shared stylesheet across all mockup versions: consistent colors, typography, spacing, and layout primitives. |
| `README.md` | Exists after the first mockup round, points to the latest version file as the canonical mockup, and may describe what the prototype demonstrates. |

Every mockup file is a valid, self-contained HTML document (`<!DOCTYPE html>`,
`<html>`, `<head>`, `<body>`). Use semantic elements such as `<header>`, `<nav>`,
`<main>`, `<section>`, and `<footer>` when the content supports them. Put CSS in
a `<style>` tag, or use `<link rel="stylesheet" href="style.css">` when a shared
stylesheet exists.

Everything a mockup needs is self-contained on disk: JavaScript appears only for
interactivity the user explicitly agreed to (animations, transitions, state
changes), and external dependencies — CDN links, web fonts, icon libraries —
likewise need explicit agreement. A static mockup is plain HTML and CSS.

Earlier versions are kept for reference. `variant-*.html` files keep their
original names once `v1.html` is seeded from the winner.

## Examples

```
<working>/prototypes/dashboard-redesign/
├── variant-a.html
├── variant-b.html
├── variant-c.html
├── v1.html
├── v2.html
├── style.css
└── README.md
```

```
<working>/plans/042-dashboard-feature/prototypes/user-settings/
├── v1.html
├── README.md
```

## Conventions

- Report the file path to the user after writing or updating a mockup.
- When Artifact or mcp__visualize is available, it previews alongside the file
  path, never in place of it.
- `README.md` is the source of truth for which version is latest.
