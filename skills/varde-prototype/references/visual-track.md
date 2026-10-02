# Frontend design track

## Understand the surface

1. Inspect the requested page or component, its neighboring routes, and the
   project's design system (guidance, tokens, component library, styles);
   preserve it unless the user asks to change it.
2. Identify the user, their main task and primary action, and constraints
   (brand, platform, viewport, accessibility). Ask only about missing details
   that would materially change the design.
3. Keep the route or component in its realistic page context, and cover the
   states that affect the design (loading, empty, validation, error, success).

## Choose a direction

If the user gave a specific direction or is refining, write the next
`v<N>.html` directly. Otherwise, make variants only
when a real structural choice is unresolved:

1. Pick 2–3 close directions or 3–5 substantially different directions;
   default to 3 and state the count.
2. Vary hierarchy, layout, and primary action; keep content and scope the same.
3. Save one complete page per direction as `variant-a.html`, `variant-b.html`,
   and so on. Give each the same fixed switcher of ordinary `<a href>` links to
   the sibling files. Do not embed or scale the pages.
4. Report the saved paths and ask the user to select a direction or hybrid.
   Stop before writing `v1.html`; after selection, seed it from that direction.

## Build and refine

- **Artifact:** a valid, self-contained HTML document with inline CSS and no
  framework, bundler, external dependency, or server. Add JavaScript, external
  assets, or the project's runtime only when the design question needs them
  and the user agrees.
- **Quality:** semantic elements, labelled controls, visible focus, readable
  contrast, and a responsive layout with a useful narrow viewport when the
  surface must adapt.
- **Revisions:** saved revisions stay unchanged; each refinement writes the
  next `v<N>.html`. When the direction is clear, make the focused refinement
  and state the assumption; otherwise ask per the round rules.

## Optional browser iteration

Open the prototype file directly when a browser tool is available; use a
running app only from a user-supplied URL or command. Never guess a URL,
route, or command.

1. Refine against actual layout and reachable interactions at the primary and
   narrow viewports, when resizing is supported.
2. Save useful screenshots beside the prototype when the tool supports it,
   and inspect them.
3. Report what you could not inspect (browser access, resizing, a state) and
   continue with the artifact.
