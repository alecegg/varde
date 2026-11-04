import test from 'node:test';
import assert from 'node:assert/strict';
import { actionItems, stateTone } from './agentsPage.ts';

const agent = (agent_id, lifecycle, idle_status = null, pending_requests = []) => ({
  agent_id,
  lifecycle,
  idle_status,
  pending_requests,
});

test('action items include pending, failed, and rate-limited agents', () => {
  const rows = [
    agent('pending', 'running', null, [{ request_id: 'r' }]),
    agent('failed', 'failed'),
    agent('limited', 'running', 'rate_limited'),
    agent('ordinary', 'running'),
  ];

  assert.deepEqual(actionItems(rows).map(({ agent_id }) => agent_id), ['pending', 'failed', 'limited']);
});

test('action items include workers awaiting a permission or question', () => {
  const rows = [agent('permission', 'awaiting_permission'), agent('question', 'awaiting_question'), agent('ordinary', 'running')];
  assert.deepEqual(actionItems(rows).map(({ agent_id }) => agent_id), ['permission', 'question']);
});

test('state tone reflects failure, rate limits, and running state', () => {
  assert.equal(stateTone(agent('failed', 'failed')), 'danger');
  assert.equal(stateTone(agent('limited', 'running', 'rate_limited')), 'stalled');
  assert.equal(stateTone(agent('running', 'running')), 'running');
  assert.equal(stateTone(agent('idle', 'idle')), 'neutral');
});
