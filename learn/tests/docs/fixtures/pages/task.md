---
type: task
status: todo
status_at:
depends_on: []
owns:
  - learn/src/varde_learn/docs/pages/__init__.py
  - learn/src/varde_learn/docs/pages/render.py
  - doc/tests/test_pages_render.py
  - doc/tests/fixtures/pages/
risk: high
---

Markdown renderer and sanitizer

Add `render_page(markdown, doc_name) -> RenderedPage` (body HTML, per-block `data-hash`, block anchors per the plan, frontmatter as a status line). - Escape-first; vocabulary and link rules exactly as in the plan Design.
- Fenced `deps` blocks call a `BLOCKS` registry entry (the graph renderer).
- Creates `pages/__init__.py`; parallel t2 adds modules but not `__init__.py`.
- Pure functions, stdlib only; no runner or workflow imports.
- Own fixtures: copies of a real plan.md and task file under `doc/tests/fixtures/pages/`.

#### Acceptance criteria

- `uv run pytest doc/tests/test_pages_render.py` → pass
- golden test: the fixture plan.md and task file render with no escaped-garbage output (nested lists, continuation lines, `**bold**`, hr, tables, fences, frontmatter status line) and HTML comments are dropped
- hostile inputs → escaped or dropped: raw HTML, `<script>`, `<svg onload>`, `javascript:` (including unicode-escaped), `data:` links, event attributes, link titles with quotes, reference-style links
- `uv run ruff check doc` → no findings

#### Progress

