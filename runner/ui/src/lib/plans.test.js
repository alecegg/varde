import test from 'node:test';
import assert from 'node:assert/strict';
import { test as vitestTest } from 'vitest';
import { nowText, queueMeta, taskTitle } from './plans.ts';

test('now text removes the next prefix used by the Now label', () => {
  assert.equal(nowText('next: seeded-run'), 'seeded-run');
});

test('degraded source names use readable labels and ignore unknown sources', async () => {
  const { degradedSourceLabels } = await import('./degradedSources.ts');
  assert.deepEqual(degradedSourceLabels(['plan_status', 'unknown', 'address_bindings']), ['plan status', 'address bindings']);
});

test('task title does not repeat an identical id', () => {
  assert.equal(taskTitle({ id: 'gaming-variants', title: 'gaming-variants' }), 'gaming-variants');
});

test('the selected queue window is Granted even when readiness is Held', () => {
  assert.match(queueMeta({ id: 'window-1', readiness: 'held' }, 'window-1'), /^Granted/);
  assert.match(queueMeta({ id: 'window-2', readiness: 'held' }, 'window-1'), /^Held/);
  assert.match(queueMeta({ id: 'window-1', readiness: 'ready' }, 'window-1'), /^Ready/);
});

test('planLabel prefers the label and falls back to the title', async () => {
  const { planLabel } = await import('./plans.ts');
  assert.equal(planLabel({ id: 'x', title: 'Full title', label: '' }), 'Full title');
  assert.equal(planLabel({ id: 'x', title: 'Full title', label: 'Short' }), 'Short');
});

test('other plan lines show identity, status, and task progress', async () => {
  const { otherPlanLine } = await import('./plans.ts');
  assert.equal(otherPlanLine({ id: 'child', title: 'Plan writers', status: 'active', done: 2, total: 5 }), 'child Plan writers · active · 2/5');
  assert.equal(otherPlanLine({ id: 'child', title: 'Plan writers', done: 2, total: 5 }), 'child Plan writers · 2/5');
});

test('task chips name every state and keep legacy in_progress as Working', async () => {
  const { taskChip, taskCounts } = await import('./plans.ts');
  const labels = ['todo', 'building', 'in_review', 'fixing', 'integrating', 'in_progress', 'done', 'blocked'].map((status) => taskChip(status).label);
  assert.deepEqual(labels, ['Todo', 'Building', 'In review', 'Fixing', 'Integrating', 'Working', 'Done', 'Blocked']);
  const queue = [{ status: 'done' }, { status: 'done' }, { status: 'in_review' }, { status: 'todo' }, { status: 'todo' }];
  assert.equal(taskCounts({ queue }), '2 done, 1 in review, 2 todo');
});

test('now line derives from task states only when a task changed after the orchestrator text', async () => {
  const { nowLine } = await import('./plans.ts');
  const queue = [{ id: 't1', title: 'Parser', status: 'integrating', status_at: '2026-10-22T10:05:00Z' }, { id: 't2', title: 'Docs', status: 'in_review', status_at: '2026-10-22T10:06:00Z' }, { id: 't3', status: 'todo' }];
  const stale = { now: 'next: wave 1', now_at: '2026-10-22T10:00:00Z', queue };
  assert.equal(nowLine(stale), 'Parser integrating, Docs in review');
  assert.equal(nowLine({ ...stale, now_at: '2026-10-22T10:30:00Z' }), 'wave 1');
  assert.equal(nowLine({ now: 'wave 1', queue }), 'Parser integrating, Docs in review');
  assert.equal(nowLine({ now: 'unknown', queue }), 'Parser integrating, Docs in review');
  assert.equal(nowLine({ now: 'unknown', queue: [] }), '');
});

test('a stalled dashboard request times out instead of waiting forever', async () => {
  const { api } = await import('./queue.ts');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (_url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
  try {
    await assert.rejects(api('/api/orchestrators', undefined, 5), { name: 'TimeoutError' });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('a plan awaiting the user is Blocked on you, never Stalled', async () => {
  const { planBadge, awaitingReason } = await import('./plans.ts');
  const plan = { activity: 'waiting', stalled: true, awaiting_user: ' sudo fs_usage capture ' };
  assert.deepEqual(planBadge(plan), { tone: 'needs-input', label: 'Blocked on you' });
  assert.equal(awaitingReason(plan), 'sudo fs_usage capture');
  assert.equal(planBadge({ activity: 'stalled', stalled: true, awaiting_user: null }).label, 'Stalled');
});

test('plan list groups by status and sorts the queue by position', async () => {
  const { groupPlans } = await import('./plans.ts');
  const rows = [
    { id: 'done', status: 'done' },
    { id: 'second', status: 'queued', queue_position: 2 },
    { id: 'active', status: 'in_progress' },
    { id: 'review', status: 'needs_review' },
    { id: 'first', status: 'queued', queue_position: 1 },
    { id: 'blocked', status: 'blocked' },
  ];
  const groups = groupPlans(rows);
  assert.deepEqual(groups.inProgress.map(({ id }) => id), ['active']);
  assert.deepEqual(groups.queued.map(({ id }) => id), ['first', 'second']);
  assert.deepEqual(groups.blocked.map(({ id }) => id), ['blocked']);
  assert.deepEqual(groups.needsReview.map(({ id }) => id), ['review']);
  assert.deepEqual(groups.done.map(({ id }) => id), ['done']);
  assert.equal(groups.blocked.length, 1);
  assert.equal(groups.needsReview.length, 1);
});

if (process.env.VITEST) {
  vitestTest('plan grouping separates blocked work and sorts the queue', async () => {
    const { groupPlans } = await import('./plans.ts');
    const groups = groupPlans([
      { id: 'blocked', status: 'blocked' },
      { id: 'review', status: 'needs_review' },
      { id: 'later', status: 'queued', queue_position: 2 },
      { id: 'earlier', status: 'queued', queue_position: 1 },
    ]);
    assert.deepEqual(groups.queued.map(({ id }) => id), ['earlier', 'later']);
    assert.deepEqual(groups.blocked.map(({ id }) => id), ['blocked']);
    assert.deepEqual(groups.needsReview.map(({ id }) => id), ['review']);
  });
}
