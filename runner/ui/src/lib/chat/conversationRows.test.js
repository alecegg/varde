import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationGroups, conversationLabel, conversationNeeds, liveConversationThreads, permissionTitle, senderName, visiblePlanThreads, visibleSenderThreads, planPreview } from './conversationRows.ts';

const thread = (agent_id, role, state = 'running', last_activity = null) => ({
  thread_key: `instance:${agent_id}`, agent_id, plan_id: null, role,
  label: role, state, last_activity,
});

test('conversation list groups live instances by role and omits archived or dead sessions', () => {
  const rows = liveConversationThreads([
    thread('one', 'builder', 'running', '2026-10-27T09:00:00Z'),
    thread('one', 'builder', 'idle', '2026-10-27T10:00:00Z'),
    thread('builder-2', 'builder', 'running', '2026-10-27T11:00:00Z'),
    thread('two', 'reviewer', 'archived'),
    thread('three', 'explorer', 'completed'),
  ]);
  assert.deepEqual(rows.map(({ agent_id, role, state }) => [agent_id, role, state]), [['builder-2', 'builder', 'running']]);
});

test('permission command titles are short and identify their sender', () => {
  assert.equal(
    permissionTitle('varde-builder', "Run command: /bin/zsh -lc 'git status'"),
    'Builder wants to run: git status',
  );
  assert.equal(permissionTitle('varde-builder', 'Approve repository access', 'Builder'), 'Approve repository access');
});

test('conversation labels preserve the configured role name', () => {
  assert.equal(conversationLabel(thread('builder-7', 'builder')), 'Builder');
  assert.equal(conversationLabel(thread('reviewer-2', 'reviewer-2')), 'Reviewer 2');
  assert.equal(conversationLabel(thread('reviewer-2', '')), 'Reviewer 2');
});

test('instance groups use exact roles and keep pending instances represented', () => {
  const groups = conversationGroups([
    thread('worker-1', 'worker', 'running', '2026-10-27T09:00:00Z'),
    thread('worker-2', 'worker', 'running', '2026-10-27T10:00:00Z'),
    thread('worker-3', 'worker', 'archived', '2026-10-27T08:00:00Z'),
    thread('reviewer-2', 'reviewer-2', 'running', '2026-10-27T11:00:00Z'),
  ], [{ agent_id: 'worker-3', pending_requests: [{ request_id: 'c' }] }]);
  assert.deepEqual(groups.map(({ thread: row, instances }) => [row.role, row.agent_id, instances.length]), [
    ['reviewer-2', 'reviewer-2', 1], ['worker', 'worker-3', 3],
  ]);
  assert.equal(conversationNeeds(groups[1].instances, [
    { agent_id: 'worker-1', pending_requests: [{ request_id: 'a' }] },
    { agent_id: 'worker-2', pending_requests: [{ request_id: 'b' }] },
    { agent_id: 'worker-3', pending_requests: [{ request_id: 'c' }] },
  ]), 3);
});

test('plan conversations include only user-facing responses', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  const rows = visiblePlanThreads([
    { thread_id: 'sender:builder', plan_id: null, title: 'Run command: /bin/zsh -lc ...', open_count: 1, last_ts: '2026-10-27T11:00:00Z', last_preview: '' },
    { thread_id: 'plan:open', plan_id: 'open', plan_title: 'Open plan', title: '', open_count: 1, last_ts: '2026-10-27T11:00:00Z', last_preview: '' },
    { thread_id: 'plan:reply', plan_id: 'reply', plan_title: 'Reply', title: 'Answer to user', open_count: 0, last_ts: '2026-10-27T11:00:00Z', last_preview: '', user_message: true },
    { thread_id: 'plan:old-reply', plan_id: 'old-reply', plan_title: 'Old reply', title: '', open_count: 0, last_ts: '2026-10-20T11:00:00Z', last_preview: '', user_message: true },
  ], now);
  assert.deepEqual(rows.map((row) => row.plan_id), ['reply']);
});

test('sender conversations include only responses to the user and sort newest first', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  const rows = visibleSenderThreads([
    { thread_id: 'sender:old', plan_id: null, title: 'Old request', open_count: 1, last_ts: '2026-10-26T11:00:00Z', last_preview: '' },
    { thread_id: 'sender:closed', plan_id: null, title: 'Resolved', open_count: 0, last_ts: '2026-10-27T11:00:00Z', last_preview: '' },
    { thread_id: 'plan:thread', plan_id: null, title: 'Plan', open_count: 1, last_ts: '2026-10-27T12:00:00Z', last_preview: '' },
    { thread_id: 'sender:new', plan_id: null, title: 'Answer to user', open_count: 0, last_ts: '2026-10-27T11:00:00Z', last_preview: '', user_message: true },
  ], now);
  assert.deepEqual(rows.map((row) => row.thread_id), ['sender:new']);
  assert.equal(permissionTitle('varde-builder', rows[0].title), 'Answer to user');
});

test('sender conversations include recent user replies but hide old closed mail', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  const rows = [
    { thread_id: 'sender:reply', last_ts: '2026-10-27T11:00:00Z', open_count: 0, user_message: true },
    { thread_id: 'sender:old-reply', last_ts: '2026-10-20T11:00:00Z', open_count: 0, user_message: true },
    { thread_id: 'sender:closed-request', last_ts: '2026-10-27T11:00:00Z', open_count: 0 },
  ];
  assert.deepEqual(visibleSenderThreads(rows, now).map((row) => row.thread_id), ['sender:reply']);
});

test('sender names hide numeric instance suffixes', () => {
  assert.equal(senderName('sender:orchestrator-5'), 'Orchestrator');
  assert.equal(senderName('reviewer-7'), 'Reviewer');
  assert.equal(senderName('ux-review-seed-agent'), 'UX Review Seed Agent');
  assert.equal(senderName('varde-builder'), 'Builder');
});

test('sender conversations collapse numbered instances to the latest role conversation', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  const rows = visibleSenderThreads([
    { thread_id: 'sender:builder-1', sender: 'builder-1', last_ts: '2026-10-27T10:00:00Z', open_count: 0, user_message: true },
    { thread_id: 'sender:builder-2', sender: 'builder-2', last_ts: '2026-10-27T11:00:00Z', open_count: 0, user_message: true },
  ], now);
  assert.deepEqual(rows.map(({ thread_id }) => thread_id), ['sender:builder-2']);
  assert.equal(senderName(rows[0].sender), 'Builder');
});

test('stale resolved plan and sender rows are omitted', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  const planRows = [
    { thread_id: 'plan:stale', plan_id: 'stale', title: 'Merged plan', open_count: 0, stale_count: 1, last_ts: '2026-10-27T11:00:00Z', last_preview: '', user_message: true },
    { thread_id: 'plan:reply', plan_id: 'reply', title: 'Fresh reply', open_count: 0, stale_count: 0, last_ts: '2026-10-27T11:00:00Z', last_preview: '', user_message: true },
  ];
  const senderRows = [
    { thread_id: 'sender:stale', plan_id: null, title: 'Answered request', open_count: 0, stale_count: 1, last_ts: '2026-10-27T11:00:00Z', user_message: true },
    { thread_id: 'sender:reply', plan_id: null, title: 'Fresh reply', open_count: 0, stale_count: 0, last_ts: '2026-10-27T11:00:00Z', user_message: true },
  ];
  assert.deepEqual(visiblePlanThreads(planRows, now).map((row) => row.plan_id), ['reply']);
  assert.deepEqual(visibleSenderThreads(senderRows, now).map((row) => row.thread_id), ['sender:reply']);
});

test('plan previews stay useful when the activity matches its title', () => {
  assert.equal(planPreview({ plan_id: 'p', plan_title: 'Deploy plan', title: 'Deploy plan', last_preview: 'Deploy plan', open_count: 1 }), 'Needs your response');
  assert.equal(planPreview({ plan_id: 'p', plan_title: 'Deploy plan', title: 'Deploy plan', last_preview: 'Deploy plan', open_count: 0 }), 'Review latest activity');
});
