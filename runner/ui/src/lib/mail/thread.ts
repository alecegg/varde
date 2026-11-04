// web/app.py list endpoints set mailbox_open per item (true when msg_id is in the open set).
// Absent means open in thread summaries; fetched detail items may omit this flag.
export type Item = Record<string, any>;
export type Thread = {
  thread_id: string;
  plan_id: string | null;
  sender: string;
  title: string;
  plan_title?: string;
  open_count: number;
  stale_count?: number;
  last_open_ts?: string;
  last_ts: string;
  last_preview: string;
  decision_ids: string[];
};

export type ThreadMail = {
  thread: Thread;
  decisions: Item[];
  openIds: string[];
  sent: Record<string, { text: string; sent_at: string } | null>;
};

export function normalizeThreadMail(value: ThreadMail | null): ThreadMail | null {
  if (!value) return value;
  const decisions = Array.isArray(value.decisions) ? value.decisions : [];
  const openIds = Array.isArray(value.openIds)
    ? value.openIds.filter((id): id is string => typeof id === 'string')
    : decisions.flatMap((item) => item.mailbox_open && typeof item.msg_id === 'string' ? [item.msg_id] : []);
  return { ...value, decisions, openIds };
}

const USER_NEEDS_KINDS = new Set(['needs-user', 'needs-decision', 'permission', 'merge-ready']);

export function isUserFacingItem(item: Item): boolean {
  return USER_NEEDS_KINDS.has(item.kind) || item.type === 'approval' || String(item.to ?? '').toLowerCase() === 'user' || String(item.from ?? item.sender ?? '').toLowerCase() === 'user' || Boolean(item.reply);
}

export function userFacingItems(items: Item[]): Item[] {
  return items.filter(isUserFacingItem);
}

export function threadForRoute(threads: ThreadMail[], routeId: string): ThreadMail | undefined {
  return threads.find(({ thread }) => thread.thread_id === routeId || encodeURIComponent(thread.thread_id) === routeId);
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

export async function loadThreads(): Promise<ThreadMail[]> {
  const threads = await fetchJson<Thread[]>('/api/threads');
  const ids = [...new Set(threads.flatMap((thread) => thread.decision_ids ?? []))];
  const summaries: Item[] = [];
  for (let index = 0; index < ids.length; index += 100) {
    const params = new URLSearchParams();
    ids.slice(index, index + 100).forEach((id) => params.append('ids', id));
    const batch = await fetchJson<{ items: Item[] }>(`/api/mailbox?${params}`);
    summaries.push(...batch.items);
  }
  const summaryById = new Map(summaries.map((item) => [item.msg_id, item]));
  const openIds = new Set(summaries.filter((item) => item.mailbox_open).map((item) => item.msg_id));
  const details = await Promise.all([...openIds].map((id) => fetchJson<Item>(`/api/mailbox/${encodeURIComponent(id)}`).catch(() => null)));
  const detailById = new Map(details.filter((item): item is Item => Boolean(item?.msg_id)).map((item) => [item.msg_id, item]));
  return threads.map((thread) => {
    const threadOpenIds = (thread.decision_ids ?? []).filter((id) => openIds.has(id));
    const decisions = userFacingItems((thread.decision_ids ?? [])
      .map((id) => ({ ...summaryById.get(id), ...detailById.get(id), msg_id: id, mailbox_open: threadOpenIds.includes(id) })));
    return {
      thread,
      decisions,
      openIds: threadOpenIds,
      sent: Object.fromEntries(decisions.map((item) => [item.msg_id, item.reply ? { text: item.reply, sent_at: item.sent_at } : null])),
    };
  });
}

export function onSnapshot(topics: string[], callback: (updated: string[]) => void): () => void {
  const listener = (event: Event) => {
    const updated = (event as CustomEvent<{ topics?: string[] }>).detail?.topics ?? [];
    if (topics.some((topic) => updated.includes(topic))) callback(updated);
  };
  window.addEventListener('runner:snapshot', listener);
  return () => window.removeEventListener('runner:snapshot', listener);
}

const seenKey = 'varde:thread-seen';

export function readSeen(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(seenKey) ?? '{}'); } catch { return {}; }
}

export function markSeen(thread: Thread) {
  try { localStorage.setItem(seenKey, JSON.stringify({ ...readSeen(), [thread.thread_id]: thread.last_ts })); } catch { /* Unread state is best effort. */ }
}

export function markUnread(thread: Thread) {
  const { [thread.thread_id]: _removed, ...rest } = readSeen();
  try { localStorage.setItem(seenKey, JSON.stringify(rest)); } catch { /* Unread state is best effort. */ }
}

export const isUnread = (thread: Thread, seen: Record<string, string>) => seen[thread.thread_id] !== thread.last_ts;

export type ThreadState = 'open' | 'recent' | 'older' | 'resolved';
export const OLDER_DAYS = 2;
const DAY_MS = 86400000;

export const planOf = (thread: Thread): string => thread.plan_id || (thread.thread_id.startsWith('plan:') ? thread.thread_id.slice(5) : '');
export const pendingIds = (thread: Thread, byId: Map<string, Item>) => thread.decision_ids.filter((id) => byId.get(id)?.state === 'pending');
export function threadState(thread: Thread, days = OLDER_DAYS, now = Date.now()): ThreadState {
  if (thread.open_count > 0) return 'open';
  if (!thread.stale_count) return 'resolved';
  return now - Date.parse(thread.last_ts) >= days * DAY_MS ? 'older' : 'recent';
}

export type Folder = 'needs-you' | 'all' | 'resolved';
export function filterThreads(threads: Thread[], folder: Folder, state: (thread: Thread) => ThreadState): Thread[] {
  if (folder === 'needs-you') return threads.filter((thread) => state(thread) === 'open');
  if (folder === 'resolved') return threads.filter((thread) => state(thread) === 'resolved');
  return threads;
}

export const isNonOpenPending = (state: ThreadState) => state === 'recent' || state === 'older';

const ANSWER_LABELS: Record<string, string> = { APPROVED: 'Approved', HOLD: 'Held', 'ASK-MORE': 'Ask more' };
export function answerLabel(text: string): string { // Approval answers are stored as "ASK-MORE: question".
  const match = /^(APPROVED|HOLD|ASK-MORE)(?::\s*([\s\S]*))?$/.exec(text.trim());
  if (!match) return text;
  return match[2] ? `${ANSWER_LABELS[match[1]]}: ${match[2]}` : ANSWER_LABELS[match[1]];
}

export const previewOf = (thread: Thread): string =>
  (thread.last_preview || thread.title || '').split('\n').map((line) => line.replace(/^[\s#>*-]+|[*`]+/g, '').trim()).find(Boolean) ?? '';

export function searchThreads(threads: Thread[], query: string): Thread[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return threads;
  return threads.filter((thread) => [thread.plan_id, thread.sender, thread.title, thread.last_preview].join(' ').toLowerCase().includes(needle));
}

/** "2026-10-21-plans-page-grouping" becomes "Plans page grouping". */
export const humanizeSlug = (slug: string) => {
  const words = slug.replace(/^\d{4}-\d{2}-\d{2}-/, '').replace(/[-_]+/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : slug;
};
export function threadName(thread: Thread): string {
  if (thread.plan_title) return thread.plan_title;
  const plan = planOf(thread);
  if (plan) return humanizeSlug(plan);
  const sender = thread.sender || '';
  if (thread.thread_id.startsWith('sender:')) return humanizeSlug((sender || thread.thread_id.slice('sender:'.length)).replace(/^varde-/i, ''));
  if (/^(?:varde-|sender:)/i.test(sender)) return humanizeSlug(sender.replace(/^(?:sender:|varde-)/, ''));
  return sender || thread.title || 'Mail thread';
}

export function threadDecisions(thread: Thread, byId: Map<string, Item>): Item[] {
  return thread.decision_ids
    .map((id) => byId.get(id))
    .filter((item): item is Item => Boolean(item))
    .sort((a, b) => Date.parse(a.ts ?? '') - Date.parse(b.ts ?? ''));
}

export function formatWhen(timestamp: unknown, now = new Date()): string {
  if (typeof timestamp !== 'string' || Number.isNaN(Date.parse(timestamp))) return '';
  const when = new Date(timestamp);
  const days = Math.floor((now.getTime() - when.getTime()) / 86400000);
  if (when.toDateString() === now.toDateString()) return when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (days < 2) return 'Yesterday';
  if (days < 7) return when.toLocaleDateString([], { weekday: 'short' });
  return when.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export const optionLabel = (option: any): string => typeof option === 'string' ? option : option?.label ?? option?.id ?? 'Option';
export const questionText = (item: Item): string => item.asked || item.subject || item.body || '';
export const decisionTitle = (item: Item): string => item.title || questionText(item) || 'Question needs context';
export const isOpen = (item: Item, openIds: readonly string[]) => item.mailbox_open !== false && openIds.includes(item.msg_id);
export const decisionType = (item: Item): 'permission' | 'approval' | 'info' | 'question' =>
  item.kind === 'permission' ? 'permission' : item.type === 'approval' ? 'approval' : item.type === 'info' ? 'info' : 'question';
