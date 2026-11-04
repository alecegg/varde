import assert from 'node:assert/strict';
import test from 'node:test';
import { needsYouRows } from './needsYouRows.ts';

const thread = (thread_id, plan_id, decisions, open_count = decisions.length) => ({
  thread: { thread_id, plan_id, sender: 'plan-1', title: '', open_count },
  decisions,
  openIds: [],
  sent: {},
});

const agent = {
  agent_id: 'builder-1', name: 'Builder', harness: 'test', role: 'builder',
  workspace: null, lifecycle: 'running', idle_status: null,
  capabilities: { respond: true },
  pending_requests: [{ request_id: 'permission-1', kind: 'permission', summary: 'Allow?' }],
};

test('counts open plan decisions and live permissions once while skipping stale items', () => {
  const rows = needsYouRows([
    thread('plan:plan-1', 'plan-1', [
      { msg_id: 'question', kind: 'needs-user', mailbox_open: true },
      { msg_id: '', kind: 'needs-user', mailbox_open: true },
      { kind: 'needs-user', mailbox_open: true },
      { msg_id: 'stale', kind: 'needs-user', mailbox_open: false },
      { msg_id: 'permission', kind: 'permission', request_id: 'permission-1', mailbox_open: true },
    ]),
  ], [agent]);

  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => row.kind), ['thread', 'permission']);
  assert.equal(rows[0].value.thread.plan_id, 'plan-1');
});
