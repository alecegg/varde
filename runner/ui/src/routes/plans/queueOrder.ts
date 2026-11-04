import { api } from '../../lib/queue';
import { reorderByDrag } from '../../lib/dragReorder';

export function reorderQueue(ids: string[], fromIndex: number, toIndex: number): string[] {
  return reorderByDrag(ids, fromIndex, toIndex);
}

export function queueMoveAnnouncement(label: string, position: number, total: number): string {
  return `${label} moved to position ${position} of ${total}.`;
}

export async function moveQueuedPlan(planId: string, direction: 'up' | 'down'): Promise<void> {
  await api('/api/queue/move', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ plan: planId, direction })
  });
}

export async function persistQueueOrder(previous: string[], next: string[]): Promise<void> {
  const working = [...previous];
  for (let targetIndex = 0; targetIndex < next.length; targetIndex += 1) {
    const currentIndex = working.indexOf(next[targetIndex]);
    if (currentIndex !== targetIndex) {
      const direction = currentIndex > targetIndex ? 'up' : 'down';
      await moveQueuedPlan(working[currentIndex], direction);
      const [item] = working.splice(currentIndex, 1);
      working.splice(currentIndex + (direction === 'up' ? -1 : 1), 0, item);
    }
  }
}
