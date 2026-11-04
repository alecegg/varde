export type QueueRow = { id: string; title: string; label?: string; purpose?: string; status: string; open_comments: number };
export type QueueCategory = { id: string; limit: number; used: number; waiting: QueueRow[]; next_up: string | null; priority_set: boolean };
export type QueueSnapshot = { categories: QueueCategory[]; hidden: { id: string; title: string; status: string; reason: string }[]; slots: { used: number; limit: number } };
export type PlanComment = { id: string; ts: string; target: string; text: string; state: 'open' | 'addressed'; kind: 'stored' | 'sent'; actor?: string; resolution_note?: string };
export type PlanDetail = { id: string; title: string; label?: string; group_name?: string; status: string; plan_text: string; tasks: { id: string; title: string; status: string; acceptance_criteria: string[] }[]; notes_status: string; review_status: string; comments: PlanComment[] };

export async function api<T>(url: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const signal = timeoutMs === undefined
    ? init?.signal
    : init?.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
  const response = await fetch(url, { cache: 'no-store', ...init, ...(signal ? { signal } : {}) });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
