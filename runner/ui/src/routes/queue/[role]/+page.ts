import { redirect } from '@sveltejs/kit';

export const prerender = false;

export function load({ params }: { params: { role: string } }) {
  redirect(307, `/thread/${encodeURIComponent(params.role)}`);
}

export type RoleQueueRow = {
  id: string;
  title: string;
  plan_id: string | null;
  state: 'running' | 'waiting' | 'blocked' | 'done';
};

export type RoleQueueSummary = {
  role: string;
  agent_id: string | null;
  state: 'needs_you' | 'running' | 'idle' | 'done';
  current: RoleQueueRow | null;
  queued: number;
  needs_you: number;
};

export type RoleQueue = { summary: RoleQueueSummary; rows: RoleQueueRow[] };
