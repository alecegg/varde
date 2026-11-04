---
type: task
status: done
depends_on: [packaging-spike]
owns: [spikes/worktree-writes/]
---

Measured (shared lock). On the packaging workspace layout, measure by phase, N=5: fresh-worktree first use (git checkout excluding committed fixture blobs, uv sync with shared UV_CACHE_DIR, first varde --version and first index command) and the dev loop (edit + scoped pytest) against the previous core-edit reference (3.87 GB, root-trace-results.md:11). State the pycache policy. Estimate the test-execution share of previous's full-gate writes (language-independent floor).

#### Acceptance criteria

- assert: `python3 -c "import json;[json.load(open('/Users/alec/source/varde-py/spikes/worktree-writes/results/%s.json'%n))['runs']>=5 or 1/0 for n in ('worktree','devloop')]"` → exit 0
- retrieve: `/Users/alec/source/varde-py/spikes/worktree-writes/results/floor.md` → test-execution share and what a port can and cannot remove

#### Progress

