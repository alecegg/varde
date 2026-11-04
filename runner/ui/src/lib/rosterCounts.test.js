import { describe, expect, it } from 'vitest';
import { rosterCounts } from './rosterCounts.ts';

describe('rosterCounts', () => {
  it('counts live agents by roster role', () => {
    const agents = [
      { role: 'builder', lifecycle: 'running' },
      { role: 'builder', lifecycle: 'idle' },
      { role: 'builder', lifecycle: 'completed' },
      { role: 'reviewer', lifecycle: 'archived' },
      { role: 'manager-bot', lifecycle: 'running' },
      { role: 'unknown', lifecycle: 'running' },
    ];
    const roles = [{ role: 'builder' }, { role: 'reviewer' }, { role: 'manager' }, { role: 'other' }];

    expect(rosterCounts(agents, roles)).toEqual({ builder: 2, reviewer: 0, manager: 1, other: 1 });
  });
});
