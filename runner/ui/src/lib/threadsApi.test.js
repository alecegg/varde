import test from 'node:test';
import assert from 'node:assert/strict';
import { threadsForTask } from './threadsApi.ts';

test('plan work items list only instances assigned by their workspace', () => {
  const threads = [
    { agent_id: 'builder-1', label: 'Builder', plan_id: 'plan', role: 'builder' },
    { agent_id: 'builder-2', label: 'Builder', plan_id: 'plan', role: 'builder' },
  ];
  assert.deepEqual(threadsForTask(
    { id: 't7-threads-ui', title: 'Threads UI' },
    threads,
    { 'builder-1': 'worktree/plan-t7-threads-ui', 'builder-2': 'worktree/plan-t6-takeover' },
  ), [threads[0]]);
});
