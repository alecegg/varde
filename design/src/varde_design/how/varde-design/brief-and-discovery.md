---
topic: varde-design/brief-and-discovery
version: 1
summary: Brief handling, survey reuse and which starter file to copy when the project has no design system
---

## Brief
Write five lines before markup (user task, the one primary action, data fields, states, density). List the material you have (data, copy, images). Ask once for what is missing; show a visible placeholder for at most two missing facts, and invent no figures, logos or quotes.

## Discover
Run `varde design survey`. Reuse the project's tokens, components and best pages. With none, say so, copy `starters/app-screen.html` (app or form), `landing-page.html` or `reading-page.html`, and write tokens first.

## Build
Build with real data and every state rendered (empty, loading, error, populated, long). Run `varde design check <file> --static-only` after each edit until no `fail`.
