import { describe, expect, it } from 'vitest';
import { chatChips, needsYouTotal, statusLine } from './chatChips.ts';

const summary = (role, state, extra = {}) => ({
  role,
  agent_id: role,
  state,
  current: null,
  queued: 0,
  needs_you: 0,
  ...extra,
});

const manager = (roleEnabled = true, extra = {}) => ({
  id: 'manager', label: 'Manager', threadKey: 'main', roleEnabled, ...extra,
});

describe('chat chips', () => {
  it('puts Manager first and maps attention counts and status dots', () => {
    const chips = chatChips([
      summary('builder', 'needs_you', { needs_you: 2 }),
      summary('worker', 'running', { queued: 1 }),
    ], manager());

    expect(chips.map(({ id }) => id)).toEqual(['manager', 'builder', 'worker']);
    expect(chips[1]).toMatchObject({ dot: 'needs-you', needsYou: 2, href: '/thread/builder' });
    expect(chips[2]).toMatchObject({ dot: 'queued', needsYou: 0, href: '/thread/worker' });
    expect(needsYouTotal(chips)).toBe(2);
    expect(statusLine(chips)).toBe('0 running, 1 queued');
  });

  it('marks a disabled manager without a status dot', () => {
    expect(chatChips([], manager(false))[0]).toMatchObject({
      id: 'manager', label: 'Manager', initials: 'MG', hue: 'violet', dot: null, disabled: true, href: '/thread/manager',
    });
  });

  it('uses the approved initials and hues for prototype agents', () => {
    const chips = chatChips(
      ['builder', 'reviewer', 'planner', 'explorer'].map((role) => summary(role, 'idle')),
      manager(),
    );

    expect(chips.map(({ label, initials, hue }) => [label, initials, hue])).toEqual([
      ['Manager', 'MG', 'violet'],
      ['Builder', 'BU', 'blue'],
      ['Reviewer', 'RE', 'green'],
      ['Planner', 'PL', 'orange'],
      ['Explorer', 'EX', 'pink'],
    ]);
  });

  it('keeps running state dots when an agent also has pending attention', () => {
    const [worker] = chatChips([summary('worker', 'running', { needs_you: 2 })], manager()).slice(1);

    expect(worker.dot).toBe('running');
  });

  it('assigns stable hues from the five-color palette', () => {
    const first = chatChips([summary('stable-agent', 'idle')], manager())[1];
    const second = chatChips([summary('stable-agent', 'running')], manager())[1];

    expect(first.hue).toBe(second.hue);
    expect(['violet', 'blue', 'green', 'orange', 'pink']).toContain(first.hue);
  });

  it('returns only Manager for an empty list', () => {
    expect(chatChips([], manager()).map(({ id }) => id)).toEqual(['manager']);
  });

  it('does not render the manager summary twice as an agent chip', () => {
    expect(chatChips([summary('manager', 'running', { agent_id: 'manager' })], manager()).map(({ id }) => id))
      .toEqual(['manager']);
  });
});
