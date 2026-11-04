import test from 'node:test';
import assert from 'node:assert/strict';
import { chatRows, toggleChatPin } from './pins.ts';

test('chat pins remove pinned threads and put needs-action threads first', () => {
    assert.deepEqual(chatRows([
      { id: 'old', needs: 0, sortKey: 1 },
      { id: 'needs', needs: 1, sortKey: 2 },
      { id: 'pinned', needs: 0, sortKey: 3 },
    ], ['pinned']), [
      { id: 'needs', needs: 1, sortKey: 2 },
      { id: 'old', needs: 0, sortKey: 1 },
    ]);
  });

test('chat pins add and remove immutably', () => {
    assert.deepEqual(toggleChatPin(['a'], 'b'), ['a', 'b']);
    assert.deepEqual(toggleChatPin(['a', 'b'], 'a'), ['b']);
});
