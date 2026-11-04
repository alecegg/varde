import { afterEach, describe, expect, it, vi } from 'vitest';
import { persistQueueOrder, queueMoveAnnouncement, reorderQueue } from './queueOrder.ts';

afterEach(() => vi.unstubAllGlobals());

describe('plan queue order', () => {
  it('reorders items without mutating the current order', () => {
    const current = ['a', 'b', 'c'];
    expect(reorderQueue(current, 0, 2)).toEqual(['b', 'c', 'a']);
    expect(current).toEqual(['a', 'b', 'c']);
  });

  it('announces the moved plan and its new position', () => {
    expect(queueMoveAnnouncement('Plan alpha', 2, 5)).toBe('Plan alpha moved to position 2 of 5.');
  });

  it('persists each adjacent move through the existing queue API', async () => {
    const requests = [];
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      requests.push({ url, body: JSON.parse(String(init.body)) });
      return { ok: true, json: async () => ({}) };
    }));

    await persistQueueOrder(['a', 'b', 'c'], ['b', 'c', 'a']);

    expect(requests).toEqual([
      { url: '/api/queue/move', body: { plan: 'b', direction: 'up' } },
      { url: '/api/queue/move', body: { plan: 'c', direction: 'up' } }
    ]);
  });
});
