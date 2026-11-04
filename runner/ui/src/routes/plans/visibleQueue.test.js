import { describe, expect, it } from 'vitest';
import { visibleQueue } from './visibleQueue.ts';

describe('visible plan queue', () => {
  it('shows the first 20 plans and expands on request', () => {
    const plans = Array.from({ length: 67 }, (_, index) => index);
    expect(visibleQueue(plans, false)).toHaveLength(20);
    expect(visibleQueue(plans, false)).toEqual(plans.slice(0, 20));
    expect(visibleQueue(plans, true)).toEqual(plans);
  });
});
