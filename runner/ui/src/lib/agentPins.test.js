import { describe, expect, it } from 'vitest';
import { loadPins, movePin, movePinToTarget, movePinWithinGroup, orderWithPins, pinGroupPosition, savePins, togglePin } from './agentPins.ts';

const groupOf = (id) => id.startsWith('blocked') ? 'blocked' : 'rest';
const displayedPins = (pins) => [...pins.filter((id) => groupOf(id) === 'blocked'), ...pins.filter((id) => groupOf(id) !== 'blocked')];

function storageWith(value = null) {
  let stored = value;
  return {
    storage: {
      getItem(key) {
        expect(key).toBe('varde.agent-pins');
        return stored;
      },
      setItem(key, next) {
        expect(key).toBe('varde.agent-pins');
        stored = next;
      }
    },
    read: () => stored
  };
}

describe('agent pins', () => {
  it('loads valid ids and tolerates corrupt or malformed storage', () => {
    expect(loadPins(storageWith('["a", "b"]').storage)).toEqual(['a', 'b']);
    expect(loadPins(storageWith('{broken').storage)).toEqual([]);
    expect(loadPins(storageWith('{"id":"a"}').storage)).toEqual([]);
  });

  it('saves ids under the per-device key', () => {
    const { storage, read } = storageWith();
    savePins(storage, ['a', 'b']);
    expect(read()).toBe('["a","b"]');
    expect(loadPins(storage)).toEqual(['a', 'b']);
  });

  it('toggles a pin off and on without changing other order', () => {
    expect(togglePin(['a', 'b'], 'a')).toEqual(['b']);
    expect(togglePin(['a', 'b'], 'c')).toEqual(['a', 'b', 'c']);
  });

  it('moves pins one place and leaves missing or edge ids in place', () => {
    expect(movePin(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
    expect(movePin(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
    expect(movePin(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']);
    expect(movePin(['a', 'b', 'c'], 'c', 1)).toEqual(['a', 'b', 'c']);
    expect(movePin(['a', 'b'], 'missing', -1)).toEqual(['a', 'b']);
  });

  it('moves a pin within its state group and leaves the other group in place', () => {
    const pins = ['running-A', 'blocked-B', 'running-C'];
    expect(displayedPins(pins)).toEqual(['blocked-B', 'running-A', 'running-C']);
    expect(movePinWithinGroup(pins, displayedPins(pins), 'running-C', -1, groupOf))
      .toEqual(['running-C', 'blocked-B', 'running-A']);
    expect(displayedPins(movePinWithinGroup(pins, displayedPins(pins), 'running-C', -1, groupOf)))
      .toEqual(['blocked-B', 'running-C', 'running-A']);
  });

  it('refuses an earlier move across the group edge and keeps the stored order', () => {
    const pins = ['running-A', 'blocked-B'];
    expect(displayedPins(pins)).toEqual(['blocked-B', 'running-A']);
    expect(pinGroupPosition(displayedPins(pins), 'running-A', groupOf)).toEqual({ index: 0, total: 1 });
    expect(movePinWithinGroup(pins, displayedPins(pins), 'running-A', -1, groupOf)).toEqual(['running-A', 'blocked-B']);
    expect(movePinWithinGroup(pins, displayedPins(pins), 'blocked-B', 1, groupOf)).toEqual(['running-A', 'blocked-B']);
  });

  it('clamps a large move to the group and reports the group position', () => {
    const pins = ['running-A', 'blocked-B', 'running-C'];
    expect(pinGroupPosition(displayedPins(pins), 'running-C', groupOf)).toEqual({ index: 1, total: 2 });
    expect(movePinWithinGroup(pins, displayedPins(pins), 'running-C', 5, groupOf)).toEqual(pins);
    expect(movePinWithinGroup(pins, displayedPins(pins), 'running-A', 5, groupOf)).toEqual(['running-C', 'blocked-B', 'running-A']);
  });

  it('skips hidden pins as move neighbors and keeps their slots', () => {
    const pins = ['running-A', 'hidden-X', 'running-C'];
    expect(movePinWithinGroup(pins, ['running-A', 'running-C'], 'running-C', -1, groupOf))
      .toEqual(['running-C', 'hidden-X', 'running-A']);
    expect(movePinWithinGroup(['blocked-B', 'hidden-X', 'running-A'], ['blocked-B', 'running-A'], 'running-A', -1, groupOf))
      .toEqual(['blocked-B', 'hidden-X', 'running-A']);
    expect(movePinWithinGroup(pins, ['running-A', 'running-C'], 'hidden-X', -1, groupOf)).toEqual(pins);
  });

  it('moves a pin to a same-group drag target and refuses the other group', () => {
    const pins = ['running-A', 'blocked-B', 'running-C'];
    expect(movePinToTarget(pins, displayedPins(pins), 'running-A', { index: 1, group: 'rest' }, groupOf))
      .toEqual(['running-C', 'blocked-B', 'running-A']);
    expect(displayedPins(movePinToTarget(pins, displayedPins(pins), 'running-A', { index: 1, group: 'rest' }, groupOf)))
      .toEqual(['blocked-B', 'running-C', 'running-A']);
    expect(displayedPins(pins)).toEqual(['blocked-B', 'running-A', 'running-C']);
    expect(movePinToTarget(pins, displayedPins(pins), 'running-C', { index: 0, group: 'blocked' }, groupOf))
      .toEqual(['running-A', 'blocked-B', 'running-C']);
    expect(movePinToTarget(pins, displayedPins(pins), 'blocked-B', { index: 1, group: 'rest' }, groupOf))
      .toEqual(['running-A', 'blocked-B', 'running-C']);
  });

  it('orders existing pinned agents first and ignores vanished pins', () => {
    const agents = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    expect(orderWithPins(agents, ['c', 'gone', 'a'])).toEqual([agents[2], agents[0], agents[1]]);
  });
});
