import { describe, expect, it } from 'vitest';
import { approvalRowText, needsYouCountText, rolePageSections, statusCardModel, statusText } from './roleStatus.ts';

describe('role status card model', () => {
  it('formats the role status and queue link for each state', () => {
    expect(statusCardModel({ role: 'builder', state: 'running', current: { title: 'Ship feature' }, queued: 3, needs_you: 0 })).toEqual({
      text: 'Working on Ship feature, 3 in queue',
      href: '/thread/builder',
    });
    expect(statusCardModel({ role: 'reviewer', state: 'needs_you', current: null, queued: 0, needs_you: 2 }).text).toBe('Needs you: 2 approvals');
    expect(statusCardModel({ role: 'planner', state: 'failed', current: { title: 'Ship feature' }, queued: 3, needs_you: 0 }).text).toBe('Failed on Ship feature, 3 in queue');
    expect(statusCardModel({ role: 'planner', state: 'idle', current: null, queued: 0, needs_you: 0 }).text).toBe('Idle');
    expect(statusCardModel({ role: 'manager-bot', state: 'done', current: null, queued: 0, needs_you: 0 }).text).toBe('Done');
  });

  it('truncates long titles and encodes the role in its link', () => {
    const model = statusCardModel({ role: 'review/lead', state: 'running', current: { title: 'x'.repeat(50) }, queued: 1, needs_you: 0 });
    expect(model.text).toBe(`Working on ${'x'.repeat(40)}, 1 in queue`);
    expect(model.href).toBe('/thread/review%2Flead');
  });

  it('prefers the status line the server computed', () => {
    const model = statusCardModel({ role: 'builder', state: 'failed', current: null, queued: 2, needs_you: 0, role_status_line: 'Failed on the plan, 2 in queue' });
    expect(model.text).toBe('Failed on the plan, 2 in queue');
  });
});

describe('role status text', () => {
  it('shows a failed role with the item it was running', () => {
    expect(statusText({ role: 'builder', state: 'failed', current: { title: 'Ship feature' }, queued: 3, needs_you: 0 })).toBe('Failed on Ship feature, 3 in queue');
    expect(statusText({ role: 'builder', state: 'failed', current: null, queued: 1, needs_you: 0 })).toBe('Failed on work, 1 in queue');
  });

  it('caps the needs-you count so the label stays short', () => {
    expect(statusText({ role: 'reviewer', state: 'needs_you', current: null, queued: 0, needs_you: 2 })).toBe('Needs you: 2 approvals');
    expect(statusText({ role: 'reviewer', state: 'needs_you', current: null, queued: 0, needs_you: 12 })).toBe('Needs you: 9+ approvals');
    expect(needsYouCountText(0)).toBe('0');
    expect(needsYouCountText(9)).toBe('9');
  });

  it('counts the queue for idle roles', () => {
    expect(statusText({ role: 'planner', state: 'idle', current: null, queued: 2, needs_you: 0 })).toBe('Idle, 2 in queue');
    expect(statusText({ role: 'planner', state: 'idle', current: null, queued: 0, needs_you: 0 })).toBe('Idle');
  });
});

describe('role page sections', () => {
  it('drops sections that hold no rows', () => {
    expect(rolePageSections({ current: 0, waiting: 0, done: 0 })).toEqual([]);
    expect(rolePageSections({ current: 1, waiting: 0, done: 0 })).toEqual([{ key: 'current', title: 'Current item', count: 1 }]);
    expect(rolePageSections({ current: 0, waiting: 3, done: 2 })).toEqual([
      { key: 'waiting', title: 'Waiting items', count: 3 },
      { key: 'done', title: 'Recently done', count: 2 },
    ]);
  });

  it('keeps the sections in queue order', () => {
    expect(rolePageSections({ current: 1, waiting: 1, done: 1 }).map((section) => section.key)).toEqual(['current', 'waiting', 'done']);
  });
});

describe('role page approvals row', () => {
  it('names the approval count and caps it like the status line', () => {
    expect(approvalRowText(1)).toBe('Review 1 pending approval');
    expect(approvalRowText(2)).toBe('Review 2 pending approvals');
    expect(approvalRowText(12)).toBe('Review 9+ pending approvals');
  });
});
