---
type: task
status: done
depends_on: []
owns: [scripts/, README.md, pyproject.toml]
---

Not measured. In /Users/alec/source/varde-py:

- create task branch task/py-port-spikes (never commit to main)
- pin Python and uv (record versions; re-verify the prior pins Python 3.14.7 and uv 0.12.19 against the registry and note any change); reuse scripts/with-lock.sh and wear.sh (with-lock.sh holds the lock; wear.sh execs it)
- extend the idle gate to refuse while /Users/alec/source/agent-memory/projects/varde/working/metrics/probe/session.lock exists
- write scripts/baseline-varde.txt (git status --porcelain of /Users/alec/source/varde, a read-only reference)

#### Acceptance criteria

- assert: `test -x /Users/alec/source/varde-py/scripts/with-lock.sh && grep -c 'varde-measure.lock' /Users/alec/source/varde-py/scripts/with-lock.sh && grep -c 'session.lock' /Users/alec/source/varde-py/scripts/measure-breakdown.sh` → exit 0
- assert: `test "$(git -C /Users/alec/source/varde-py branch --show-current)" = task/py-port-spikes` → exit 0

#### Progress

