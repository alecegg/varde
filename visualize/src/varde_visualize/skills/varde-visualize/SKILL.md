---
name: varde-visualize
description: "Use this skill when the user asks for a chart, diagram, table, dashboard page or approval form built from given data or a described structure, to be served locally and returned as a URL. Covers one-shot pictures of data, proposals the user must approve, deny or comment on, and input forms."
recommends: [varde-prototype]
---

# Visualize and serve

Every visualization is one markdown page of components and parts, written as `ui` statements. If `varde learn docs blocks` fails, print its error and stop.

An existing markdown file is served directly with `varde learn docs serve <file>`; create no visualization for it.

## Outcomes

- The page is `<working>/visualizations/<slug>/<slug>.md` (kebab-case slug; `<working>` from `varde setup paths --json`, never guessed). Ask only if the slug exists.
- The page has a title, one line of context, then one `ui` fence per visual. Component fields and line syntax come from `varde learn docs blocks <type>`, never guessed (`varde learn how varde-visualize page-syntax`).
- A proposal the user must approve, deny or comment on is a `decision` component (example: `assets/decision-example.md`); an answer applies nothing.
- Use only the numbers the user gave or that you measured; invent no values. For a chart, diagram or table, also apply `references/craft.md`.
- The page passes `varde learn check <page>`.
- It is served in the background with `varde learn docs serve <page> --port 0`; the URL comes from the server output.
- The reply gives the URL first, then the file path.
- The server is stopped on request or at session end, else named.

## Safety

- Serve on 127.0.0.1 only; pass no `--host` unless the user asks.
- Write no HTML, script or remote asset; the page system renders everything.
