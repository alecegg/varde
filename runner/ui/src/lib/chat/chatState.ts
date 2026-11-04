export type ChatRole = 'user' | 'bot' | 'event';
export type ChatMessage = {
  seq: number;
  change_seq: number;
  id: string;
  thread_key: string;
  reply_to: string | null;
  role: ChatRole;
  kind: string | null;
  text: string;
  link: string | null;
  state: string;
  source_agent_id: string | null;
  source_event_seq: number | null;
  created_at: string;
  delivery?: 'sending' | 'sent' | 'failed';
};

export type OutboxItem = { id: string; text: string; state: 'sending' | 'sent' | 'failed' };

export function isUserFacingMessage(message: ChatMessage): boolean {
  return message.role !== 'event' || message.kind === 'question' || message.kind === 'handoff';
}

export function userFacingMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter(isUserFacingMessage);
}

export const PAGE_SIZE = 50;
export const MAX_MESSAGES = PAGE_SIZE * 3;
export const FOLLOW_DISTANCE_PX = 48;

export function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) {
    const previous = byId.get(message.id);
    if (!previous || message.change_seq >= previous.change_seq) byId.set(message.id, message);
  }
  return [...byId.values()].sort((a, b) => a.seq - b.seq);
}

export const shouldFollow = (distanceFromBottom: number): boolean => distanceFromBottom <= FOLLOW_DISTANCE_PX;

export function pageWindow(messages: ChatMessage[], anchorSeq: number): ChatMessage[] {
  if (messages.length <= MAX_MESSAGES) return messages;
  const anchor = messages.findIndex((message) => message.seq >= anchorSeq);
  const center = anchor < 0 ? messages.length - 1 : anchor;
  const start = Math.max(0, Math.min(center - Math.floor(MAX_MESSAGES / 2), messages.length - MAX_MESSAGES));
  return messages.slice(start, start + MAX_MESSAGES);
}

export function draftKey(threadKey: string): string { return `varde:chat:draft:${threadKey}`; }
export function outboxKey(threadKey: string): string { return `varde:chat:outbox:${threadKey}`; }
export function loadDraft(threadKey: string, storage: Storage = localStorage): string {
  try { return storage.getItem(draftKey(threadKey)) ?? ''; } catch { return ''; }
}
export function saveDraft(threadKey: string, value: string, storage: Storage = localStorage): void {
  try { if (value) storage.setItem(draftKey(threadKey), value); else storage.removeItem(draftKey(threadKey)); } catch { /* Storage is best effort. */ }
}

export function upsertOutbox(items: OutboxItem[], update: OutboxItem): OutboxItem[] {
  const index = items.findIndex((item) => item.id === update.id);
  if (index < 0) return [...items, update];
  return items.map((item, itemIndex) => itemIndex === index ? update : item);
}

export function loadOutbox(threadKey: string, storage: Storage = localStorage): OutboxItem[] {
  try {
    const items: unknown = JSON.parse(storage.getItem(outboxKey(threadKey)) ?? '[]');
    if (!Array.isArray(items)) return [];
    return items.filter((item): item is OutboxItem => item && typeof item.id === 'string' && typeof item.text === 'string' && ['sending', 'sent', 'failed'].includes(item.state))
      .map((item) => ({ ...item, state: item.state === 'sending' ? 'failed' : item.state }));
  } catch { return []; }
}

export function saveOutbox(threadKey: string, items: OutboxItem[], storage: Storage = localStorage): void {
  try {
    if (items.length) storage.setItem(outboxKey(threadKey), JSON.stringify(items));
    else storage.removeItem(outboxKey(threadKey));
  } catch { /* Storage is best effort. */ }
}

export function resumeCursor(messages: ChatMessage[]): number {
  return messages.reduce((cursor, message) => Math.max(cursor, message.change_seq), 0);
}
