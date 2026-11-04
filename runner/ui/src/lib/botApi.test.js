import test from 'node:test';
import assert from 'node:assert/strict';
import { percentage, stateLabel } from './botApi.ts';

test('percentage bounds values and handles empty budgets', () => {
  assert.equal(percentage(1, 4), 25);
  assert.equal(percentage(6, 4), 100);
  assert.equal(percentage(-1, 4), 0);
  assert.equal(percentage(1, 0), null);
});

test('state labels are stable for known and unavailable states', () => {
  assert.equal(stateLabel('running'), 'Running');
  assert.equal(stateLabel('paused'), 'Paused');
  assert.equal(stateLabel('killed'), 'Killed');
  assert.equal(stateLabel('unknown'), 'Unavailable');
});
