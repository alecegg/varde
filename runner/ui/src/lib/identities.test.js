import test from 'node:test';
import assert from 'node:assert/strict';
import { isActionAgent, isLiveAgent, rosterLines, stateLabel } from './identitiesApi.ts';

const identity = (id, role = id, count = 0) => ({ id, role, count });

test('rosterLines preserves API ordering and filters zero-count roles', () => {
  const entries = [identity('manager'), identity('builder', 'builder', 2), identity('orchestrator'), identity('other', 'other', 1), identity('reviewer')];
  assert.deepEqual(rosterLines(entries), [entries[0], entries[1], entries[2], entries[3]]);
});

test('Other is omitted when empty', () => {
  assert.deepEqual(rosterLines([identity('manager'), identity('other')]), [identity('manager')]);
});

test('pending and needs-you worker states remain action items', () => {
  for (const lifecycle of ['failed', 'awaiting_permission', 'awaiting_question']) {
    const worker = { agent_id: lifecycle, role: 'builder', lifecycle };
    assert.equal(isActionAgent(worker), true);
  }
  const pending = { agent_id: 'pending', role: 'builder', lifecycle: 'running', pending_requests: [{ kind: 'question' }] };
  assert.equal(isActionAgent(pending), true);
  assert.equal(isActionAgent({ role: 'builder', lifecycle: 'running', idle_status: 'awaiting_question' }), true);
  assert.equal(isActionAgent({ role: 'builder', lifecycle: 'running' }), false);
});

test('completed and archived sessions are excluded from the live list', () => {
  assert.equal(isLiveAgent({ lifecycle: 'completed' }), false);
  assert.equal(isLiveAgent({ lifecycle: 'archived' }), false);
  assert.equal(isLiveAgent({ lifecycle: 'running' }), true);
});

test('roster state labels use the same capitalisation', () => {
  assert.equal(stateLabel(null), 'Idle');
  assert.equal(stateLabel('idle'), 'Idle');
  assert.equal(stateLabel('running'), 'Running');
  assert.equal(stateLabel('needs you'), 'Needs you');
  assert.equal(stateLabel('failed'), 'Failed');
  assert.equal(stateLabel('archived'), 'Archived');
});
