import { describe, expect, it } from 'vitest';
import { homeRows, homeSections, idleLabel, rowDetail } from './homeList.ts';
import { getHome } from './homeApi.ts';

const summary = (role, state, agent_id = null, extra = {}) => ({
  role, agent_id, state, current: null, queued: 0, needs_you: 0, ...extra,
});

describe('home rows', () => {
  it('groups by attention state and orders pins within each group', () => {
    const rows = [
      summary('idle', 'idle', 'idle-id'),
      summary('working', 'running', 'working-id'),
      summary('needs', 'needs_you', 'needs-id'),
      summary('other-needs', 'needs_you', 'other-id'),
      summary('done', 'done', 'done-id', { completed_at: new Date().toISOString() }),
    ];

    expect(homeRows(rows, ['other-id', 'working-id', 'needs-id']).map(({ role }) => role))
      .toEqual(['other-needs', 'needs', 'working', 'idle', 'done']);
  });

  it('lists a failed role right after needs-you roles', () => {
    const rows = [
      summary('boot-pending', 'needs_you', 'boot-id'),
      summary('broken', 'failed', 'broken-id'),
      summary('working', 'running', 'working-id'),
      summary('idle', 'idle', 'idle-id'),
      summary('done', 'done', 'done-id', { completed_at: new Date().toISOString() }),
    ];

    expect(homeRows(rows, []).map(({ role }) => role))
      .toEqual(['boot-pending', 'broken', 'working', 'idle', 'done']);
  });

  it('uses role as the pin identity when no agent id exists', () => {
    expect(homeRows([summary('planner', 'idle')], ['planner'])[0].id).toBe('planner');
  });

  it('includes only done summaries completed within the last 24 hours', () => {
    const now = Date.parse('2026-10-27T12:00:00Z');
    const rows = [
      summary('recent', 'done', 'recent', { completed_at: '2026-10-27T11:00:00Z' }),
      summary('old', 'done', 'old', { completed_at: '2026-10-26T11:59:59Z' }),
      summary('idle', 'idle', 'idle'),
    ];

    expect(homeRows(rows, [], now).map(({ role }) => role)).toEqual(['idle', 'recent']);
  });
});

describe('home sections', () => {
  it('keeps active rows in order and collapses idle rows into their own group', () => {
    const rows = [
      summary('idle-a', 'idle', 'idle-a'),
      summary('working', 'running', 'working-id'),
      summary('needs', 'needs_you', 'needs-id'),
      summary('failed', 'failed', 'failed-id'),
      summary('idle-b', 'idle', 'idle-b'),
      summary('done', 'done', 'done-id', { completed_at: new Date().toISOString() }),
    ];

    const { active, idle } = homeSections(rows, []);

    expect(active.map(({ role }) => role)).toEqual(['needs', 'failed', 'working', 'done']);
    expect(idle.map(({ role }) => role)).toEqual(['idle-a', 'idle-b']);
  });

  it('orders idle rows by their pins', () => {
    const rows = [summary('a', 'idle', 'a-id'), summary('b', 'idle', 'b-id'), summary('c', 'idle', 'c-id')];

    expect(homeSections(rows, ['c-id', 'b-id']).idle.map(({ role }) => role)).toEqual(['c', 'b', 'a']);
  });

  it('labels the collapsed idle group with its count', () => {
    expect(idleLabel(7)).toBe('7 idle');
    expect(idleLabel(1)).toBe('1 idle');
  });
});

describe('home row detail', () => {
  it('names the current item and the queue count', () => {
    expect(rowDetail({ current: { title: 'Add role status card' }, queued: 3 })).toEqual({ item: 'Add role status card', queued: '3 queued' });
  });

  it('keeps whichever part of the detail exists', () => {
    expect(rowDetail({ current: { title: 'Ship feature' }, queued: 0 })).toEqual({ item: 'Ship feature', queued: null });
    expect(rowDetail({ current: null, queued: 2 })).toEqual({ item: null, queued: '2 queued' });
    expect(rowDetail({ current: null, queued: 0 })).toEqual({ item: null, queued: null });
  });
});

describe('home API', () => {
  it('fetches home summaries without caching', async () => {
    const originalFetch = globalThis.fetch;
    let request;
    globalThis.fetch = async (...args) => {
      request = args;
      return { ok: true, json: async () => ({ roles: [] }) };
    };
    try {
      await expect(getHome()).resolves.toEqual({ roles: [] });
      expect(request).toEqual(['/api/home', { cache: 'no-store' }]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('reports failed home requests', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => ({ ok: false, status: 503 });
    try {
      await expect(getHome()).rejects.toThrow('Request failed (503)');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
