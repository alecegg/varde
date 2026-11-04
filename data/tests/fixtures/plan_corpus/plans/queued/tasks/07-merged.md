---
custom_key: "preserve this" # task comment
type: task
status: merged
status_at:
depends_on: [example-dependency]
owns: [runner/src/varde_runner/web/jobs_route.py, runner/src/varde_runner/web/app.py, runner/tests/test_jobs_api.py]
---

Add the /api/jobs routes and wire the registry into the app

Contract in plan "API / interface contracts". Put handlers in web/jobs_route.py; in app.py only construct the store-backed controller, register routes, and add `Route("/jobs", _ui_shell)`. Keep the edit to app.py minimal (others edit it).

#### Acceptance criteria

- assert: `core/scripts/test-env.sh uv run pytest runner/tests/test_jobs_api.py -q` → passes

#### Progress
