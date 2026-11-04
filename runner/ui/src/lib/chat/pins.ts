export type ChatRow = { id: string; needs: number; sortKey: number };

export function chatRows<T extends ChatRow>(rows: T[], pinned: string[]): T[] {
  const pinSet = new Set(pinned);
  return [...rows]
    .filter((row) => !pinSet.has(row.id))
    .sort((a, b) => Number(b.needs > 0) - Number(a.needs > 0) || b.sortKey - a.sortKey);
}

export function toggleChatPin(pinned: string[], id: string): string[] {
  return pinned.includes(id) ? pinned.filter((item) => item !== id) : [...pinned, id];
}
