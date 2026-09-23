#!/usr/bin/env bash
set -euo pipefail

git init -q
git config user.email "eval@example.invalid"
git config user.name "Varde Eval"

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
parent: 2026-09-18-active
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
    mkdir -p src/queue
    cat > src/queue/worker.ts <<'SOURCE'
export function retryDelay(): number {
  return 1000;
}
SOURCE
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
parent: 2026-08-10-manage-command
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
    ;;
  8)
    mkdir -p memory-bank/working/plans/2026-09-20-retry-policy
    cat > memory-bank/working/plans/2026-09-20-retry-policy/plan.md <<'PLAN'
---
status: active
title: Retry policy
type: plan
shape: single
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
  9)
    mkdir -p src
    cat > src/cache.ts <<'SOURCE'
export function invalidateCache(key: string): boolean {
  return key.length > 0;
}
SOURCE
    ;;
  10)
    mkdir -p src
    cat > src/cache.ts <<'SOURCE'
export function invalidateCache(key: string): boolean {
  return key.length > 0;
}
SOURCE
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
    mkdir -p src
    cat > src/parser.ts <<'SOURCE'
export function parse(_input: string): string {
  return "broken";
}
SOURCE
    ;;
  *)
    printf 'unsupported change eval id: %s\n' "$EVAL_ID" >&2
    exit 2
    ;;
esac

git add .
git commit -qm "seed eval $EVAL_ID"
