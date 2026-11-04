export type AgentWatchEvent = {
  seq: number;
  kind: string;
  payload: unknown;
  created_at?: string;
};

export type AgentWatchSnapshot = {
  last_seq: number;
  events: AgentWatchEvent[];
  open_intents?: unknown[];
  pending_waits?: unknown[];
  truncated?: boolean;
};

export const MAX_WATCH_EVENTS = 50;

let tabClientId: string | null = null;

export function getTabWatchClientId(): string {
  if (tabClientId === null) {
    tabClientId = `dashboard-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
  }
  return tabClientId;
}

export function agentWatchUrl(agentId: string, after: number | null): string {
  const query = new URLSearchParams({ client: getTabWatchClientId(), role: 'observer' });
  if (after !== null) query.set('after', String(after));
  return `/api/agents/${encodeURIComponent(agentId)}/watch?${query}`;
}
