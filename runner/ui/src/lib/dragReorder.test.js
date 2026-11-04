import { describe, expect, it } from 'vitest';
import { reorderByDrag } from './dragReorder.ts';

describe('reorderByDrag', () => {
  it('moves an item forward or backward to the target index', () => {
    expect(reorderByDrag(['a', 'b', 'c', 'd'], 1, 3)).toEqual(['a', 'c', 'd', 'b']);
    expect(reorderByDrag(['a', 'b', 'c', 'd'], 3, 0)).toEqual(['d', 'a', 'b', 'c']);
  });

  it('returns a copy for same or invalid indices', () => {
    const ids = ['a', 'b'];
    expect(reorderByDrag(ids, 0, 0)).toEqual(ids);
    expect(reorderByDrag(ids, -1, 0)).toEqual(ids);
    expect(reorderByDrag(ids, 0, 2)).toEqual(ids);
    expect(reorderByDrag(ids, 0, Number.NaN)).toEqual(ids);
    expect(reorderByDrag(ids, 0, 1)).not.toBe(ids);
  });
});
