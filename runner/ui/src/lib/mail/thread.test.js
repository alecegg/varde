import test from 'node:test';
import assert from 'node:assert/strict';
import { isUserFacingItem, normalizeThreadMail, threadForRoute, threadName, userFacingItems } from './thread.ts';

test('normalizes cached thread mail across legacy and incomplete shapes', () => {
  const cached = {
    thread: { thread_id: 'sender:builder' },
    openIds: {},
    decisions: [{ msg_id: 'open', mailbox_open: true }, { msg_id: 'closed', mailbox_open: false }],
    sent: {},
  };
  assert.deepEqual(normalizeThreadMail(cached)?.openIds, ['open']);
  assert.deepEqual(normalizeThreadMail({ ...cached, decisions: undefined, openIds: {} })?.decisions, []);
  assert.deepEqual(normalizeThreadMail({ ...cached, decisions: undefined, openIds: {} })?.openIds, []);
  assert.equal(normalizeThreadMail(null), null);
});

test('mailbox thread lookup accepts encoded sender IDs from route segments', () => {
  const mail = { thread: { thread_id: 'sender:builder-123' } };
  assert.equal(threadForRoute([mail], 'sender:builder-123'), mail);
  assert.equal(threadForRoute([mail], 'sender%3Abuilder-123'), mail);
  assert.equal(threadForRoute([mail], 'sender:other'), undefined);
});

test('sender mailbox titles humanize runner role names', () => {
  assert.equal(threadName({ thread_id: 'sender:varde-builder', sender: 'varde-builder', title: 'Run command', plan_id: null }), 'Builder');
  assert.equal(threadName({ thread_id: 'sender:builder-1', sender: 'builder-1', title: '', plan_id: null }), 'Builder 1');
});

test('thread items omit session-manager chatter and keep needs-you and user messages', () => {
  const items = [
    { msg_id: 'request', kind: 'needs-user' },
    { msg_id: 'permission', kind: 'permission' },
    { msg_id: 'manager-milestone', kind: 'info', to: 'main' },
    { msg_id: 'response', kind: 'info', to: 'user' },
    { msg_id: 'user-message', kind: 'info', from: 'user' },
    { msg_id: 'user-reply', kind: 'info', reply: 'Decided yes' },
    { msg_id: 'worker-chat', kind: 'info', to: 'reviewer' },
    { msg_id: 'notice', kind: 'info-failure' },
  ];
  assert.deepEqual(userFacingItems(items).map((item) => item.msg_id), ['request', 'permission', 'response', 'user-message', 'user-reply']);
  assert.equal(isUserFacingItem({ kind: 'info', to: 'user' }), true);
  assert.equal(isUserFacingItem({ kind: 'info', to: 'main' }), false);
});
