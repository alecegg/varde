import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeMessages, pageWindow, resumeCursor, saveDraft, loadDraft, loadOutbox, saveOutbox, upsertOutbox, shouldFollow, userFacingMessages, MAX_MESSAGES } from './chatState.ts';

const row = (seq, id = String(seq), change_seq = seq) => ({ seq, change_seq, id, thread_key: 'main', reply_to: null, role: 'bot', kind: null, text: id, link: null, state: 'sent', source_agent_id: null, source_event_seq: null, created_at: '' });

test('merges by id, applies later changes, and orders by sequence', () => {
  const merged = mergeMessages([row(2), row(1)], [row(2, '2', 5), row(3)]);
  assert.deepEqual(merged.map((item) => item.seq), [1, 2, 3]);
  assert.equal(merged[1].change_seq, 5);
});

test('follows only when the viewport is within 48 pixels of the bottom', () => {
  assert.equal(shouldFollow(48), true);
  assert.equal(shouldFollow(49), false);
});

test('chat timelines omit internal event rows but retain user questions and handoffs', () => {
  const events = [
    { ...row(1), role: 'event', kind: 'wait_created' },
    { ...row(2), role: 'event', kind: 'question' },
    { ...row(3), role: 'event', kind: 'handoff' },
    { ...row(4), role: 'event', kind: 'answer' },
    row(5, 'user', 5),
  ];
  assert.deepEqual(userFacingMessages(events).map((message) => message.seq), [2, 3, 5]);
});

test('keeps at most three pages centered around the visible anchor', () => {
  const messages = Array.from({ length: 200 }, (_, index) => row(index + 1));
  const windowed = pageWindow(messages, 80);
  assert.equal(windowed.length, MAX_MESSAGES);
  assert.ok(windowed.some((message) => message.seq === 80));
  assert.equal(resumeCursor(windowed), 154);
});

test('stores drafts per thread and updates outbox rows by id', () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
  saveDraft('main', 'hello', storage);
  assert.equal(loadDraft('main', storage), 'hello');
  assert.equal(loadDraft('instance:x', storage), '');
  assert.deepEqual(upsertOutbox([{ id: 'a', text: 'x', state: 'sending' }], { id: 'a', text: 'x', state: 'failed' }), [{ id: 'a', text: 'x', state: 'failed' }]);
  saveOutbox('main', [{ id: 'a', text: 'x', state: 'sending' }], storage);
  assert.deepEqual(loadOutbox('main', storage), [{ id: 'a', text: 'x', state: 'failed' }]);
  assert.deepEqual(loadOutbox('instance:x', storage), []);
});
