---
status: backlog
title: "Interactive docs (HTML or MDX output tool)"
label: "Interactive served docs"
group: "docs"
type: plan
depends_on: []
shared:
  - pyproject.toml
  - uv.lock
  - docs/sandbox-permissions.md   # t4 adds loopback note, then t7 adds Chromium cache note
  - learn/src/varde_learn/docs/help/
  - learn/src/varde_learn/docs/cli.py
gate: []
reviewed_commit: "8cad65bb69a1ff8394b1b966e4f52800f2f1109f"
reviewed_on: "2026-10-30"
---

## Problem

Plans, reviews, explainers, docs and agent-doc reviews are plain markdown with no inline comments or visualizations, and the runner dashboard is the only commenting surface (plans only).

## Solution

`varde learn docs serve <doc>` serves any stored markdown file as a sanitized, mobile-friendly page with inline comments and live updates; comments land in a jsonl beside the doc and reach the author agent through `varde learn docs watch`. Pilot kind: plans, with a task dependency graph block. Reference: https://www.builder.io/blog/claude-code-plan.

## Non-goals

- MDX, agent-written HTML, arbitrary JS charts, iframe sandboxes.
- Replacing markdown as the stored source.
- Any dependency on runner code, routes, or a running runner.
- Runner import of the new comment file (optional later; nothing depends on it).
- Changing the runner plan-comment flow (`plans/<id>/comments.jsonl`).

## Constraints

- Module placement obeys `layers.toml`: `doc` is level 1 and may depend only on `core`; no imports from `runner`, `workflow`, or `data`.
- Stdlib HTTP server and SSE; no new runtime dependencies (a markdown subset is parsed in-module).
- Skills stay goal-not-how; rare steps go in a small how topic.

## Design

### Tech choices

- Module: `doc` (`learn/src/varde_learn/docs/pages/`) — level 1, already owns the `varde learn docs` CLI and depends only on `core`; a new module would add layers.toml, preset and install cost for no gain.
- Command group `varde learn docs` (not `varde learn docss`) — `varde learn docs` is the existing CLI; `docs` would be a second group.
- Renderer: escape-first markdown subset to HTML — mirrors the runner's `markdown.ts` approach, but is a new Python implementation.
- Block vocabulary (in): headings, paragraphs, nested lists, list items with indented continuation lines, task lists, tables, blockquote, horizontal rule, fenced code, inline code/bold/emphasis, links, fenced `deps` graph block, frontmatter as a status line. Out: raw HTML (shown escaped), HTML comments (dropped), images, footnotes.
- Links: http, https and `#` render as anchors; relative links render as plain text with the target in a title — the server serves only the doc; other schemes render as text.
### Security and delivery

- Security: bind 127.0.0.1 on a random port; Host must be `127.0.0.1:<port>` or `localhost:<port>` on every route (GET `/`, `/events`, static, POST); per-run token delivered in a page meta tag and required on POST (never printed in the URL); POST needs `Content-Type: application/json`, a body cap (64 KiB), a text cap (8000 chars) and `Origin` exactly `http://127.0.0.1:<port>` or `http://localhost:<port>`.
- Headers on every response: CSP `default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. One fixed first-party script and stylesheet, no inline script or `style=` attributes, no author JS.
### Layout and live update

- Layout: single column, max width about 70ch, viewport meta, touch targets at least 44px, no horizontal page scroll (tables and code scroll inside their block).
- Live update: SSE `/events`; one shared poller thread (0.5 s mtime and comments size) feeds all clients; `daemon_threads = True`, heartbeat comment every 15 s, clean shutdown on Ctrl-C; the client refetches the body, keeps any open comment composer text, and highlights blocks whose content hash changed.
- Comment anchor: heading slug, or `<heading-slug>/<n>` for the nth block in that section, plus a `quote` of the first 80 chars so edited docs can show orphaned comments.
- Comment file: `<doc-path>.comments.jsonl` beside the doc (for example `plan.md.comments.jsonl`) — the plan dir's `comments.jsonl` belongs to the runner flow and its `target` schema.
- Dependency graph: the `deps` fence holds lines `task-id: dep, dep`; rendered as fixed server-side inline SVG, layered by dependency depth, using presentation attributes or CSS classes only (no `style=`).
- Playwright — added to the doc module `[dependency-groups]` dev group and `uv lock` run (already in the lock via runner); the browser test is `slow`-marked with a copied lazy-launch fixture.
- Verification — tasks use `uv run` and module tests only; deploying and installed-CLI checks (`varde learn docs ...`) are the orchestrator's post-merge step.

### Schema / data model

- Comment row: `{id, ts, anchor, quote, text, state: "open", actor}`; schema copied from `runner/src/varde_runner/comments.py` (which uses `target`), not imported.
- Event rows: `{id, ts, event: "addressed", note}` and `{id, ts, state: "open"|"resolved"}`.
- Fold: latest event wins; `addressed` carries `resolution_note`; unparseable lines are skipped.

### API / interface contracts

- `varde learn docs serve <doc> [--port N] [--open]` — prints the URL; foreground until interrupted.
- `varde learn docs watch <doc> [--all] [--interval <N>s|<N>m]` — default interval 2s; prints only comments added after start, `--all` also prints the open backlog first; one line per comment: `comment <id> <anchor> <text-truncated-120>`; exits on interrupt; run under the harness monitor.
- `varde learn docs comments <doc> [--open] [--json]` — full text.
- `varde learn docs reply <doc> <comment-id> --note <text>` — appends `addressed`; unknown id is an error.
- HTTP: `GET /` page, `GET /events` SSE, `GET /static/app.js|app.css`, `POST /comments` (JSON `{anchor, quote, text}`, token header).

## Decisions so far

- HTML vs MDX → sanitized HTML rendered from markdown; MDX out.
- Where served → standalone `varde learn docs serve`; runner-independent, no runner routes.
- Comment storage → append-only jsonl beside the doc, anchored by doc path plus heading or block slug, any doc kind.
- Delivery to author → `varde learn docs watch` under harness monitor; reply via `varde learn docs reply`; page shows the reply.
- Pilot kind → plans; first visualization → fixed `deps` graph.
- Safe rendering and mobile layout → plan decisions (see Design).
- watch backlog → new comments only by default, `--all` for the backlog.
- Relative links → plain text with title.
- Playwright → doc dev dependency group.
- t6 how topic → kept, limited to resuming after page comments; goal line separates served-page comments from runner-dashboard comments.
- Browser check → separate slow-tier task t7.
- Placement → `doc` module; command group `varde learn docs`.

## Open Questions

n/a — no open questions

## Assumptions

- `uv run playwright` Chromium is available in the dev environment, as for runner browser tests — affects: AC (browser check) — confidence: high.
- Comments are written by a single local user; no authentication beyond the per-run token and loopback binding — affects: design — confidence: high.

## Acceptance criteria

- [ ] Given a plan.md with headings, a table and a `deps` fence
      When `varde learn docs serve plan.md` is open in a browser
      Then it renders sanitized HTML (this plan.md and a task file render with no escaped-garbage output) including an SVG dependency graph, with no script other than the first-party app.js
      (assert: `uv run pytest doc/tests -k "pages and not browser"` → pass)
- [ ] Given markdown containing raw HTML, `<script>`, `javascript:` links and event attributes
      When rendered
      Then none survive unescaped
      (assert: `uv run pytest doc/tests/test_pages_render.py` → pass)
- [ ] Given the page is open
      When the user submits a comment on a block
      Then a row is appended to `<doc>.comments.jsonl` with the block anchor and quote, and the page lists it
      (assert: `uv run pytest doc/tests/test_pages_server.py` → pass)
- [ ] Given `varde learn docs watch plan.md` is running
      When a comment is added
      Then exactly one line naming id and anchor is printed
      (assert: `uv run pytest doc/tests/test_pages_cli.py` → pass)
- [ ] Given an open comment
      When the agent runs `varde learn docs reply <doc> <id> --note "done"`
      Then the page shows the note under the comment without reload
      (assert: `uv run pytest doc/tests/test_pages_browser.py -m slow -k reply` → pass)
- [ ] Given the source file changes
      When the open page receives the SSE event
      Then changed blocks are highlighted and unchanged blocks are not
      (assert: `uv run pytest doc/tests/test_pages_browser.py -m slow -k highlight` → pass)
- [ ] Given a 390px-wide viewport
      When the page loads
      Then there is no horizontal page scroll and comment controls are at least 44px
      (assert: `uv run pytest doc/tests/test_pages_browser.py -m slow -k mobile` → pass)
- [ ] Given the new code
      When layer rules run
      Then `doc` imports only `varde_core` and no runner code
      (assert: `bash -c 'source core/scripts/test-env.sh; uv run pytest core/tests/test_dependency_rules.py core/tests/test_layer_couplings.py'` → pass)
- [ ] Given a planner or orchestrator reads varde-plan
      When it wants user feedback on a draft
      Then the skill points to serving the plan and running `varde learn docs watch` under the monitor
      (assert: `uv run varde learn check` and `uv run varde learn check` on varde-plan → pass; retrieve: a varde-agent-doc-authoring review of the edited skill → no blocking finding)

## Progress

- 2026-10-30 independent review applied (notes/plan-review.md).
- 2026-10-30 drafted from user decisions; decomposed into 7 tasks.

## Related

- Queue note: plans/2026-10-25-native-cutover/notes/post-gate-queue.md (sections: Queued 2026-10-29 (user): explore two plans, item 2)
- Format reference only: runner/src/varde_runner/comments.py, runner/ui/src/lib/markdown.ts
