import { serverErrors } from './profileForm.ts';

export type IdentityInstance = { agent_id: string; label: string; state: string };
export type Identity = {
  id: string; name: string; label: string; description: string; role: string;
  count: number; worst_state: string | null; hue?: string; initials?: string;
  instances: IdentityInstance[] | null; error?: string;
};
export type ProfileFields = { name: string; label: string; description: string };

export class IdentitySaveError extends Error {
  readonly errors: Record<string, string>;

  constructor(errors: Record<string, string>, message = 'Could not save profile') {
    super(message);
    this.name = 'IdentitySaveError';
    this.errors = errors;
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not load identities (${response.status})`);
  return response.json();
}

export async function listIdentities(): Promise<Identity[]> {
  return (await get<{ identities: Identity[] }>('/api/identities')).identities;
}

export async function identityInstances(id: string): Promise<IdentityInstance[]> {
  return (await get<{ instances: IdentityInstance[] }>(`/api/identities/${encodeURIComponent(id)}/instances?include=all`)).instances;
}

export function profileHref(id: string): string {
  return `/agents/profile/${encodeURIComponent(id)}`;
}

export async function saveIdentity(id: string, fields: ProfileFields): Promise<Identity> {
  const response = await fetch(`/api/identities/${encodeURIComponent(id)}`, {
    method: 'PUT',
    cache: 'no-store',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(fields),
  });
  let body: unknown;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const errors = response.status === 400 ? serverErrors(body) : {};
    if (response.status === 400) throw new IdentitySaveError(errors);
    throw new Error(`Could not save profile (${response.status})`);
  }
  return body as Identity;
}

const expandedRoles = new Set(['orchestrator']);
export function rosterLines(identities: Identity[]): Identity[] {
  return identities
    .filter((identity) => identity.id === 'manager' || expandedRoles.has(identity.role) || identity.count > 0)
    .filter((identity) => identity.id !== 'other' || identity.count > 0);
}

export function isActionAgent(agent: { lifecycle?: unknown; idle_status?: unknown; pending_requests?: readonly unknown[] }): boolean {
  const lifecycle = String(agent.lifecycle ?? '').toLowerCase();
  const idleStatus = String(agent.idle_status ?? '').toLowerCase();
  const needsAttention = ['failed', 'rate_limited', 'awaiting_permission', 'awaiting_question'];
  return (agent.pending_requests?.length ?? 0) > 0 || needsAttention.includes(lifecycle) || needsAttention.includes(idleStatus);
}

export function isLiveAgent(agent: { lifecycle?: unknown }): boolean {
  return !['completed', 'archived'].includes(String(agent.lifecycle ?? '').toLowerCase());
}

const STATE_LABELS: Record<string, string> = { failed: 'Failed', 'needs you': 'Needs you', running: 'Running' };

export function stateLabel(state: string | null | undefined): string {
  const text = (state ?? '').trim();
  if (!text) return 'Idle';
  return STATE_LABELS[text] ?? `${text[0].toUpperCase()}${text.slice(1)}`;
}

export function stateTone(state: string | null | undefined): 'blocked' | 'needs-input' | 'running' | 'idle' {
  if (state === 'failed') return 'blocked';
  if (state === 'needs you') return 'needs-input';
  if (state === 'running') return 'running';
  return 'idle';
}
