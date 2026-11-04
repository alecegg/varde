import test from 'node:test';
import assert from 'node:assert/strict';
import { mailboxItemAction, needsYouAnswerText, needsYouOptionLabel, needsYouRefreshFailureMessage, shortenNeedsYou } from './needsYouShort.ts';

test('shows the first three items and reports the remainder', () => {
  assert.deepEqual(shortenNeedsYou(['urgent', 'next', 'later', 'last']), {
    items: ['urgent', 'next', 'later'],
    moreCount: 1
  });
});

test('classifies question and permission mailbox items from their kind or type', () => {
  assert.equal(mailboxItemAction({ kind: 'question' }), 'question');
  assert.equal(mailboxItemAction({ type: 'question' }), 'question');
  assert.equal(mailboxItemAction({ kind: 'permission' }), 'permission');
  assert.equal(mailboxItemAction({ type: 'approval' }), 'permission');
  assert.equal(mailboxItemAction({}), 'other');
});

test('handles fewer items and a zero limit', () => {
  assert.deepEqual(shortenNeedsYou(['urgent', 'next']), { items: ['urgent', 'next'], moreCount: 0 });
  assert.deepEqual(shortenNeedsYou(['urgent'], 0), { items: [], moreCount: 1 });
});

test('uses the visible label for selectable question options', () => {
  assert.equal(needsYouOptionLabel('Mobile navigation'), 'Mobile navigation');
  assert.equal(needsYouOptionLabel({ label: 'Plan workflows', id: 'plan' }), 'Plan workflows');
  assert.equal(needsYouOptionLabel({ id: 'plan' }), 'plan');
});

test('keeps the submitted free-text answer or selected option for the thread', () => {
  assert.equal(needsYouAnswerText('  Details here  ', 'Mobile navigation'), 'Details here');
  assert.equal(needsYouAnswerText('', 'Mobile navigation'), 'Mobile navigation');
});

test('uses a retry failure state instead of an empty state when refresh failed', () => {
  assert.match(needsYouRefreshFailureMessage('', ['plan status'], 0), /could not be refreshed/);
  assert.equal(needsYouRefreshFailureMessage('', ['plan status'], 1), null);
  assert.equal(needsYouRefreshFailureMessage('', [], 0), null);
  assert.equal(needsYouRefreshFailureMessage('Connection failed', [], 0), 'Connection failed');
});
