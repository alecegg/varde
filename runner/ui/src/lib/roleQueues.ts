export type RoleQueueItem = {
  id: string;
  state: string;
  claimed_by: string | null;
  claim_expires_at: string | null;
  depends_on: string[];
  serialize_with: string[];
};

export type RoleQueue = {
  role: string;
  queued: number;
  claimed: number;
  ready: number;
  items: RoleQueueItem[];
};

export type RoleQueuesData = {
  roles: RoleQueue[];
  budget: {
    snapshot: { providers: Record<string, number>; rss_mb: number; cpu_pct: number; processes: number; live_workers: number } | null;
    limits: { provider_max: Record<string, number>; rss_mb_max: number; cpu_pct_max: number; processes_max: number; global_worker_ceiling: number } | null;
    decision: { ok: boolean; reason: string };
  };
  metrics: {
    cycle_seconds: Record<string, number | null>;
    idle_seconds: Record<string, number>;
  };
};

export type ItemTone = 'blocked' | 'success' | 'waiting' | 'neutral';

const IN_FLIGHT_STATES = new Set(['claimed', 'building', 'in_review']);

export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

export function budgetPercent(value: number | undefined, limit: number | undefined): number | null {
  if (value == null || limit == null || !Number.isFinite(value) || !Number.isFinite(limit) || limit <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((value / limit) * 100)));
}

/** Reason a queued item cannot start, using only item fields the role-queues route returns. */
export function blockedReason(item: RoleQueueItem, states: ReadonlyMap<string, string>): string | null {
  if (item.state !== 'queued') return null;
  const unmerged = item.depends_on.find((id) => states.get(id) !== 'merged');
  if (unmerged) return `Depends on unmerged item ${unmerged}`;
  const busy = item.serialize_with.find((id) => IN_FLIGHT_STATES.has(states.get(id) ?? ''));
  return busy ? `Serialized with in-flight item ${busy}` : null;
}

export function itemTone(item: RoleQueueItem, reason: string | null): ItemTone {
  if (reason) return 'blocked';
  if (item.state === 'queued') return 'success';
  return IN_FLIGHT_STATES.has(item.state) ? 'waiting' : 'neutral';
}

export function budgetTone(ok: boolean): Exclude<ItemTone, 'waiting'> {
  return ok ? 'success' : 'blocked';
}

export function expiryLabel(value: string | null, now = Date.now()): string {
  if (!value) return 'No lease expiry';
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return 'Lease expiry unavailable';
  const remaining = Math.round((time - now) / 1000);
  return remaining <= 0 ? 'Lease expired' : `Lease ${duration(remaining)} left`;
}
