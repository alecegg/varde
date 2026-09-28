#!/usr/bin/env bash
set -euo pipefail

git init -q
git config user.email "eval@example.invalid"
git config user.name "Varde Eval"

# Plain JavaScript fixtures run with Node's built-in test runner; no deps.
write_node_package() {
  cat > package.json <<PACKAGE
{
  "name": "$1",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test"
  }
}
PACKAGE
}

case "$EVAL_ID" in
  1)
    mkdir -p memory-bank/working/plans/2026-09-18-active/tasks
    mkdir -p memory-bank/working/handoffs/2026-09-19-open
    cat > memory-bank/working/plans/2026-09-18-active/plan.md <<'PLAN'
---
status: active
title: Active fixture
type: plan
---

## Acceptance criteria

- [ ] Fixture remains active.
PLAN
    cat > memory-bank/working/plans/2026-09-18-active/tasks/fixture.md <<'TASK'
---
type: task
status: todo
depends_on: []
modifies: []
creates: []
---

Fixture task.
TASK
    cat > memory-bank/working/handoffs/2026-09-19-open/handoff.md <<'HANDOFF'
---
type: handoff
status: open
description: Open fixture handoff.
---

# Open fixture
HANDOFF
    ;;
  2)
    mkdir -p src
    cat > src/api.ts <<'SOURCE'
export function handlePublicRequest(): string {
  return "ok";
}
SOURCE
    ;;
  3)
    mkdir -p src/queue test
    write_node_package worker-fixture
    cat > src/queue/worker.mjs <<'SOURCE'
const BASE_DELAY_MS = 1000;

// Delay before retry number `attempt` (1 for the first retry).
export function retryDelay(attempt) {
  return BASE_DELAY_MS;
}
SOURCE
    cat > test/worker.test.mjs <<'TEST'
import assert from "node:assert/strict";
import test from "node:test";
import { retryDelay } from "../src/queue/worker.mjs";

test("retryDelay returns a positive delay", () => {
  const delay = retryDelay(1);
  assert.ok(Number.isFinite(delay) && delay > 0);
});
TEST
    ;;
  4)
    mkdir -p memory-bank/working/plans/2026-08-10-manage-command/tasks src
    cat > memory-bank/working/plans/2026-08-10-manage-command/plan.md <<'PLAN'
---
status: active
title: Manage command
type: plan
---

## Acceptance criteria

- [x] The manage command source exists.
  - assert: `test -f src/manage.ts`
- [x] The manage command exports its entry point.
  - retrieve: `src/manage.ts` contains `export function manage`
- [x] The compatibility checker remains available.
  - assert: `manage-compat-check`
- [x] The manage command returns the legacy value.
  - retrieve: `src/manage.ts` contains `return "legacy"`
PLAN
    cat > memory-bank/working/plans/2026-08-10-manage-command/tasks/implementation.md <<'TASK'
---
type: task
status: done
depends_on: []
modifies: [src/manage.ts]
creates: []
---

Implement the manage command.
TASK
    cat > src/manage.ts <<'SOURCE'
export function manage(): string {
  return "ready";
}
SOURCE
    ;;
  5|7)
    mkdir -p memory-bank/working/plans/notifications/schema
    mkdir -p memory-bank/working/plans/notifications/delivery
    cat > memory-bank/working/plans/notifications/plan.md <<'PLAN'
---
status: active
title: Notifications feature
type: plan
shape: group
---

## Acceptance criteria

- [ ] Notifications can be delivered.
PLAN
    cat > memory-bank/working/plans/notifications/schema/plan.md <<'PLAN'
---
status: backlog
title: Notification schema
type: plan
depends_on: []
---

## Acceptance criteria

- [ ] Notification records have a stable schema.
PLAN
    cat > memory-bank/working/plans/notifications/delivery/plan.md <<'PLAN'
---
status: backlog
title: Notification delivery
type: plan
depends_on: [schema]
---

## Acceptance criteria

- [ ] Notifications reach configured channels.
PLAN
    if [[ "$EVAL_ID" == 7 ]]; then
      mkdir -p memory-bank/working/plans/notifications/schema/tasks
      cat > memory-bank/working/plans/notifications/schema/tasks/design-schema.md <<'TASK'
---
type: task
status: blocked
depends_on: []
modifies: []
creates: []
---

Design the notification record schema.

#### Progress

- blocked: schema shape needs a product decision (JSON vs. protobuf) not yet made
TASK
    fi
    ;;
  8)
    mkdir -p memory-bank/working/plans/2026-09-20-retry-policy
    cat > memory-bank/working/plans/2026-09-20-retry-policy/plan.md <<'PLAN'
---
status: active
title: Retry policy
type: plan
---

## Problem

Retry limits lack one stable public function.

## Solution

Create `src/retry-policy.ts` with `maxAttempts` returning `5`.

## Non-goals

- Change other retry behavior.

## Constraints

- Keep the function synchronous.

## Acceptance criteria

- [ ] The retry policy source exists.
  - assert: `test -f src/retry-policy.ts`
- [ ] The retry policy returns five attempts.
  - retrieve: `src/retry-policy.ts` contains `return 5`
PLAN
    ;;
  9|10)
    mkdir -p src test
    write_node_package cache-fixture
    cat > src/cache.mjs <<'SOURCE'
// In-memory cache keyed by namespaced strings such as "user:42".
export function createCache() {
  const entries = new Map();
  return {
    get(key) {
      return entries.get(key);
    },
    set(key, value) {
      entries.set(key, value);
    },
    has(key) {
      return entries.has(key);
    },
    // Drop cached entries for a key namespace after the source data changes.
    invalidate(prefix) {
      entries.delete(prefix);
    },
  };
}
SOURCE
    cat > test/cache.test.mjs <<'TEST'
import assert from "node:assert/strict";
import test from "node:test";
import { createCache } from "../src/cache.mjs";

test("stores and returns values", () => {
  const cache = createCache();
  cache.set("session:1", "abc");
  assert.equal(cache.get("session:1"), "abc");
});
TEST
    cat > ISSUE.md <<'ISSUE'
# Stale user profiles after the last release

After a profile update the service calls `cache.invalidate("user")`, but
`cache.get("user:42")` keeps returning the old profile until the process
restarts. Before the last release the same call made the next read miss the
cache. `npm test` still passes.
ISSUE
    ;;
  11)
    mkdir -p src
    cat > src/parser.ts <<'SOURCE'
export function parse(input: string): string {
  return input;
}
SOURCE
    ;;
  12)
    mkdir -p src test
    write_node_package parser-fixture
    cat > src/parser.mjs <<'SOURCE'
export function parse(_input) {
  return "broken";
}
SOURCE
    cat > test/parser.test.mjs <<'TEST'
import assert from "node:assert/strict";
import test from "node:test";
import { parse } from "../src/parser.mjs";

test("parse returns fixed", () => {
  assert.equal(parse("input"), "fixed");
});
TEST
    ;;
  13)
    mkdir -p memory-bank/working/plans/2026-09-01-alpha
    cat > memory-bank/working/plans/2026-09-01-alpha/plan.md <<'PLAN'
---
status: backlog
title: Alpha fixture
type: plan
---

## Problem

Fixture problem.

## Solution

Fixture solution.

## Open Questions

- n/a — resolved during planning
PLAN
    mkdir -p memory-bank/working/plans/2026-09-02-beta-draft
    cat > memory-bank/working/plans/2026-09-02-beta-draft/plan.md <<'PLAN'
---
status: backlog
title: Beta fixture
type: plan
---

## Problem

Fixture problem.

## Solution

Fixture solution.

## Open Questions

- **Which timeout?** Blocks rollout. Recommendation: 30s — matches existing defaults.
PLAN
    ;;
  14)
    mkdir -p memory-bank/working/plans/2026-09-21-logger-fix/tasks src
    cat > memory-bank/working/plans/2026-09-21-logger-fix/plan.md <<'PLAN'
---
status: active
title: Logger fix
type: plan
---

## Problem

The logger drops the last message before exit.

## Solution

Flush the logger's buffer in `src/logger.ts` before exit.

## Acceptance criteria

- [ ] Buffered messages are flushed on exit.
  - assert: `src/logger.ts`'s `close()` calls `flush()` before returning
PLAN
    cat > memory-bank/working/plans/2026-09-21-logger-fix/tasks/flush-on-exit.md <<'TASK'
---
type: task
status: todo
depends_on: []
modifies: ["src/logger.ts"]
creates: []
---

Flush the logger buffer before process exit.

#### Test approach

profile: tdd
rationale: exit flushing is a regression risk with no existing coverage.

#### Out of scope

- Changing the logger's public API.

#### Verification

- assert: `src/logger.ts`'s `close()` calls `flush()` before returning → present
TASK
    cat > src/logger.ts <<'SOURCE'
export class Logger {
  private buffer: string[] = [];

  log(message: string): void {
    this.buffer.push(message);
  }

  close(): void {
    this.buffer = [];
  }
}
SOURCE
    ;;
  15)
    mkdir -p memory-bank/working/plans/2026-09-10-widget-exporter-draft
    cat > memory-bank/working/plans/2026-09-10-widget-exporter-draft/plan.md <<'PLAN'
---
status: backlog
title: Widget exporter
type: plan
---

## Problem

Widgets can't be exported to CSV.

## Solution

Add a `--csv` flag to the export command.

## Acceptance criteria

- Given a widget list, when `--csv` is passed, then output is valid CSV.

## Open Questions

- n/a — resolved during planning
PLAN
    ;;
  16)
    mkdir -p config redirected/working redirected/knowledge
    cat > config/paths.toml <<'CONFIG'
[default]
working = "redirected/working"
knowledge = "redirected/knowledge"
CONFIG
    ;;
  21)
    mkdir -p src test
    printf '%s\n' 'export function parse() { return "broken"; }' > src/parser.mjs
    printf '%s\n' '// Existing tests must remain untouched.' > test/parser.test.mjs
    ;;
  22)
    mkdir -p src test
    printf '%s\n' 'export function handleRequest(request) { return { status: 200 }; }' > src/api.mjs
    printf '%s\n' '// No account/IP limit scope has been selected.' > test/api.test.mjs
    ;;
  *)
    printf 'unsupported change eval id: %s\n' "$EVAL_ID" >&2
    exit 2
    ;;
esac

if [ "$EVAL_ID" = 15 ]; then
  # The draft plan must stay untracked after setup.
  git add . ':!memory-bank/working/plans/2026-09-10-widget-exporter-draft'
  git commit -qm "seed eval $EVAL_ID" --allow-empty
else
  git add .
  git commit -qm "seed eval $EVAL_ID"
fi
