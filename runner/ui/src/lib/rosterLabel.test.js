import { describe, expect, it } from 'vitest';
import { profileLinkLabel, profileLinkLabels } from './rosterLabel.ts';

const identity = (id, name, role = id) => ({ id, name, role });

describe('profileLinkLabels', () => {
  it('gives five roles distinct profile link labels', () => {
    const identities = [
      identity('a', 'Alice', 'manager'), identity('b', 'Bob', 'builder'),
      identity('c', 'Casey', 'reviewer'), identity('d', 'Drew', 'planner'),
      identity('e', 'Elliot', 'orchestrator'),
    ];
    const labels = Object.values(profileLinkLabels(identities));
    expect(new Set(labels).size).toBe(5);
  });

  it('falls back to ids when identities share a name', () => {
    const identities = [identity('one', 'Sam'), identity('two', 'Sam')];
    expect(profileLinkLabels(identities)).toEqual({
      one: 'Edit one profile', two: 'Edit two profile',
    });
  });

  it('falls back to the id when the name is empty', () => {
    expect(profileLinkLabel(identity('worker-1', ''))).toBe('Edit worker-1 profile');
  });
});
