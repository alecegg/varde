export type BotState = 'running' | 'paused' | 'killed' | 'unavailable';

export type BotSnapshot = {
  state: BotState;
  reason: string | null;
  changed_at: string | null;
  changed_by: string | null;
  agents: number;
  max_concurrent_agents: number;
  launches_last_hour: number;
  max_launches_per_hour: number;
  actions_last_minute: number;
  max_actions_per_minute: number;
  tokens_today: number;
  daily_token_budget: number;
};

export type BotAuditRow = {
  id: number;
  phase: string;
  action: string;
  actor: string;
  status: string;
  reason: string | null;
  agent_id: string | null;
  plan_id: string | null;
  ts: string;
};

export function percentage(value: number, total: number): number | null {
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)));
}

export function stateLabel(state: string): string {
  if (state === 'running' || state === 'paused' || state === 'killed') {
    return state[0].toUpperCase() + state.slice(1);
  }
  return 'Unavailable';
}

export async function getBotState(): Promise<BotSnapshot> {
  return request<BotSnapshot>('/api/bot/state');
}

export async function controlBot(action: 'pause' | 'resume' | 'kill'): Promise<BotSnapshot> {
  return request<BotSnapshot>('/api/bot/control', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action })
  });
}

export async function getBotAudit(before?: number): Promise<BotAuditRow[]> {
  const params = new URLSearchParams({ limit: '25' });
  if (before !== undefined) params.set('before', String(before));
  return request<BotAuditRow[]>(`/api/bot/audit?${params}`);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.error === 'string' ? body.error : `Bot request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
