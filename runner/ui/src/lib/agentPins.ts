const STORAGE_KEY = 'varde.agent-pins';

export function loadPins(storage: Storage): string[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? '[]');
    if (!Array.isArray(value)) return [];
    return [...new Set(value.filter((id): id is string => typeof id === 'string'))];
  } catch {
    return [];
  }
}

export function savePins(storage: Storage, ids: string[]): void {
  storage.setItem(STORAGE_KEY, JSON.stringify([...new Set(ids)]));
}

export function togglePin(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
}

export function movePin(ids: string[], id: string, delta: number): string[] {
  const index = ids.indexOf(id);
  if (index < 0 || !Number.isFinite(delta) || delta === 0) return [...ids];

  const nextIndex = Math.max(0, Math.min(ids.length - 1, index + Math.trunc(delta)));
  if (nextIndex === index) return [...ids];

  const next = [...ids];
  next.splice(index, 1);
  next.splice(nextIndex, 0, id);
  return next;
}

export type PinGroupOf = (id: string) => string;

export type PinTarget = { index: number; group: string };

export function pinGroupPosition(orderedIds: string[], id: string, groupOf: PinGroupOf): { index: number; total: number } {
  const group = groupOf(id);
  const peers = orderedIds.filter((peer) => groupOf(peer) === group);
  return { index: peers.indexOf(id), total: peers.length };
}

export function movePinWithinGroup(ids: string[], orderedIds: string[], id: string, delta: number, groupOf: PinGroupOf): string[] {
  const visible = orderedIds.filter((visibleId) => ids.includes(visibleId));
  if (!visible.includes(id) || !Number.isFinite(delta) || delta === 0) return [...ids];

  const group = groupOf(id);
  const peers = visible.filter((peer) => groupOf(peer) === group);
  const peerIndex = peers.indexOf(id);
  const nextIndex = Math.max(0, Math.min(peers.length - 1, peerIndex + Math.trunc(delta)));
  if (nextIndex === peerIndex) return [...ids];

  peers.splice(peerIndex, 1);
  peers.splice(nextIndex, 0, id);
  const next = [...ids];
  const peerSlots = ids.flatMap((pinId, slot) => peers.includes(pinId) ? [slot] : []);
  peerSlots.forEach((slot, order) => { next[slot] = peers[order]; });
  return next;
}

export function movePinToTarget(ids: string[], orderedIds: string[], id: string, target: PinTarget, groupOf: PinGroupOf): string[] {
  if (target.group !== groupOf(id)) return [...ids];
  const { index } = pinGroupPosition(orderedIds, id, groupOf);
  return movePinWithinGroup(ids, orderedIds, id, target.index - index, groupOf);
}

export function orderWithPins<T extends { id: string }>(agents: T[], pins: string[]): T[] {
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const pinSet = new Set(pins);
  const pinned = pins.flatMap((id) => {
    const agent = byId.get(id);
    return agent ? [agent] : [];
  });
  const remaining = agents.filter((agent) => !pinSet.has(agent.id));
  return [...pinned, ...remaining];
}
