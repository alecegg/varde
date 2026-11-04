import { orderWithPins } from './agentPins';

export type HomeState = 'needs_you' | 'failed' | 'running' | 'idle' | 'done';

export type HomeSummary = {
  role: string;
  agent_id: string | null;
  state: HomeState;
  current: { id: string; title: string; plan_id: string | null; state: string } | null;
  queued: number;
  needs_you: number;
  completed_at?: string | null;
};

export type HomeRow = HomeSummary & { id: string };

export type HomeSections = { active: HomeRow[]; idle: HomeRow[] };

export type HomeRowDetail = { item: string | null; queued: string | null };

const GROUP_ORDER: HomeState[] = ['needs_you', 'failed', 'running', 'idle', 'done'];
const DAY_MS = 24 * 60 * 60 * 1000;

export function homeRows(summaries: HomeSummary[], pins: string[], now = Date.now()): HomeRow[] {
  const groups = new Map<HomeState, HomeRow[]>(GROUP_ORDER.map((state) => [state, []]));
  for (const summary of summaries) {
    if (summary.state === 'done' && !isRecent(summary.completed_at, now)) continue;
    groups.get(summary.state)?.push({ ...summary, id: summary.agent_id || summary.role });
  }

  return GROUP_ORDER.flatMap((state) => orderWithPins(groups.get(state) ?? [], pins));
}

export function homeSections(summaries: HomeSummary[], pins: string[], now = Date.now()): HomeSections {
  const rows = homeRows(summaries, pins, now);
  return {
    active: rows.filter((row) => row.state !== 'idle'),
    idle: rows.filter((row) => row.state === 'idle'),
  };
}

export function idleLabel(count: number): string {
  return `${count} idle`;
}

export function rowDetail(summary: Pick<HomeSummary, 'current' | 'queued'>): HomeRowDetail {
  return {
    item: summary.current?.title ?? null,
    queued: summary.queued > 0 ? `${summary.queued} queued` : null,
  };
}

function isRecent(completedAt: string | null | undefined, now: number): boolean {
  if (!completedAt) return false;
  const timestamp = Date.parse(completedAt);
  return Number.isFinite(timestamp) && timestamp >= now - DAY_MS && timestamp <= now;
}
