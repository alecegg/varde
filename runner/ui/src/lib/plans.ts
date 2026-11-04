export type Row = Record<string, any>;
export type PlanListItem = {
  id: string;
  title: string;
  label: string;
  status: 'in_progress' | 'queued' | 'blocked' | 'needs_review' | 'done';
  queue_position: number | null;
  open_comments: number;
  updated: string;
};
export type PlanGroups = {
  inProgress: PlanListItem[];
  queued: PlanListItem[];
  blocked: PlanListItem[];
  needsReview: PlanListItem[];
  done: PlanListItem[];
};
export type TaskKind = 'done' | 'run' | 'wait' | 'block' | 'pend';

const stateOf = (value: unknown) => String(value ?? '').toLowerCase();
const DONE = ['done', 'complete', 'completed'];
const ACTIVE_TASK = ['in_progress', 'building', 'in_review', 'fixing', 'integrating'];
const RUNNING = ['running', 'active', ...ACTIVE_TASK];

export const display = (value: unknown) => (typeof value === 'string' && value ? value : 'Not reported');
export const known = (value: unknown) => typeof value === 'string' && value !== '' && value.toLowerCase() !== 'unknown';

export function statusState(value: unknown): 'blocked' | 'needs-input' | 'done' | 'running' | 'idle' | 'unknown' {
  const state = stateOf(value);
  if (state.includes('block')) return 'blocked';
  if (state.includes('decision') || state.includes('input') || state.includes('ask')) return 'needs-input';
  if (DONE.includes(state)) return 'done';
  if (RUNNING.includes(state)) return 'running';
  if (['todo', 'idle', 'stale', 'backlog'].includes(state)) return 'idle';
  return 'unknown';
}

export function taskKind(status: unknown): TaskKind {
  const state = statusState(status);
  if (state === 'done') return 'done';
  if (state === 'running') return 'run';
  if (state === 'blocked') return 'block';
  if (state === 'needs-input') return 'wait';
  return 'pend';
}

export const awaitingReason = (plan: Row) => (typeof plan.awaiting_user === 'string' ? plan.awaiting_user.trim() : '');
export const planId = (plan: Row) => String(plan.plan_id ?? plan.id);
export const tasksOf = (plan: Row): Row[] => plan.queue ?? [];
export const doneTasks = (plan: Row) => tasksOf(plan).filter((task) => statusState(task.status) === 'done').length;
export const progressPercent = (plan: Row) => (tasksOf(plan).length ? Math.round((doneTasks(plan) / tasksOf(plan).length) * 100) : 0);

export function planBadge(plan: Row): { tone: 'running' | 'needs-input' | 'blocked' | 'success' | 'idle' | 'stalled'; label: string } {
  if (!awaitingReason(plan) && plan.stalled === true) return { tone: 'stalled', label: 'Stalled' };
  const state = String(plan.activity ?? 'unknown');
  const labels: Record<string, string> = { running: 'Running', waiting: 'Blocked on you', stalled: 'Stalled', idle: 'Idle', backlog: 'Backlog', blocked: 'Blocked', done: 'Done', unknown: 'Unknown' };
  const tone = state === 'done' ? 'success' : state === 'blocked' ? 'blocked' : state === 'waiting' ? 'needs-input' : state === 'running' ? 'running' : state === 'stalled' ? 'stalled' : 'idle';
  return { tone, label: labels[state] ?? 'Unknown' };
}

export function idleText(seconds: unknown): string {
  if (typeof seconds !== 'number' || seconds <= 0) return '';
  if (seconds < 60) return 'Idle for less than a minute';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Idle for ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `Idle for ${hours}h ${minutes % 60}m` : `Idle for ${Math.floor(hours / 24)}d`;
}
export const runningWorkers = (plan: Row): Row[] => (plan.workers ?? []).filter((worker: Row) => statusState(worker.status) === 'running');

export const infraProblems = (infrastructure: Row[]) => infrastructure.filter((agent) => !['running', 'alive', 'idle'].includes(String(agent.status ?? '').toLowerCase()));

type ChipTone = 'idle' | 'running' | 'waiting' | 'stalled' | 'success' | 'blocked';
const TASK_CHIPS: Record<string, { tone: ChipTone; label: string }> = {
  done: { tone: 'success', label: 'Done' },
  blocked: { tone: 'blocked', label: 'Blocked' },
  in_progress: { tone: 'running', label: 'Working' },
  building: { tone: 'running', label: 'Building' },
  in_review: { tone: 'waiting', label: 'In review' },
  fixing: { tone: 'stalled', label: 'Fixing' },
  integrating: { tone: 'running', label: 'Integrating' },
  todo: { tone: 'idle', label: 'Todo' },
};

// State chip for a task; a state the dashboard does not know shows its raw text.
export function taskChip(status: unknown): { tone: ChipTone; label: string } {
  const state = stateOf(status);
  return TASK_CHIPS[state] ?? { tone: 'idle', label: display(status) };
}

// "2 done, 1 in review, 2 todo": one count per state, in the order of TASK_CHIPS.
export function taskCounts(plan: Row): string {
  const counts = new Map<string, number>();
  for (const task of tasksOf(plan)) {
    const state = stateOf(task.status);
    const key = DONE.includes(state) ? 'done' : state in TASK_CHIPS ? state : 'todo';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Object.keys(TASK_CHIPS).filter((state) => counts.has(state)).map((state) => `${counts.get(state)} ${TASK_CHIPS[state].label.toLowerCase()}`).join(', ');
}

const timeOf = (value: unknown) => (typeof value === 'string' ? Date.parse(value) : Number.NaN);

// The orchestrator's Now text, unless a task changed state after it was written; then a line from task states.
export function nowLine(plan: Row): string {
  const text = nowText(plan.now);
  const written = timeOf(plan.now_at); // missing now_at is NaN: task states win
  const active = tasksOf(plan).filter((task) => ACTIVE_TASK.includes(stateOf(task.status)));
  const newest = Math.max(...active.map((task) => timeOf(task.status_at)).filter(Number.isFinite), Number.NEGATIVE_INFINITY);
  const textMissing = !text || text === 'unknown';
  const taskStateIsNewer = Number.isFinite(newest) && (!Number.isFinite(written) || newest > written);
  if (!active.length || !(textMissing || taskStateIsNewer)) return textMissing ? '' : text;
  const shown = active.slice(0, 3).map((task) => `${display(task.title ?? task.id)} ${taskChip(task.status).label.toLowerCase()}`);
  return shown.join(', ') + (active.length > 3 ? `, +${active.length - 3} more` : '');
}

// Owner shown beside the state chip; the chip already names the state.
export const taskNote = (task: Row) => (task.owner ? String(task.owner) : '');
export const planLabel = (plan: Row) => String(plan.label || plan.title || planId(plan));
export const groupOf = (plan: Row) => (typeof plan.group_name === 'string' ? plan.group_name.trim() : '');
export const otherPlanLine = (plan: Row) => {
  const status = typeof plan.status === 'string' ? plan.status.trim() : '';
  const statusText = status ? ` · ${status}` : '';
  return `${display(plan.id)} ${display(plan.title)}${statusText} · ${plan.done ?? 0}/${plan.total ?? 0}`;
};

export const needsYou = (plans: Row[]) => plans.filter((plan) => plan.activity === 'waiting');

export const nowText = (value: unknown) => String(value ?? '').replace(/^next:\s*/i, '');

export function taskTitle(task: Row): string {
  const title = display(task.title ?? task.id);
  return task.title && task.title !== task.id ? `${task.id} ${title}` : title;
}

export function ageLabel(value: unknown, now = Date.now()): string {
  const parsed = typeof value === 'string' ? Date.parse(value) : Number.NaN;
  if (!Number.isFinite(parsed)) return 'No recent event';
  const minutes = Math.max(0, Math.floor((now - parsed) / 60000));
  if (minutes < 1) return 'Just now';
  return minutes < 60 ? `${minutes}m ago` : `${Math.floor(minutes / 60)}h ago`;
}

export function queueMeta(row: Row, grantedWindow?: string | null): string {
  const readinessLabels: Record<string, string> = {
    ready: 'Ready',
    'needs-review': 'Needs review',
    draft: 'Draft',
    held: 'Held',
  };
  const currentReadiness = row.readiness ?? row.status;
  const readiness = row.id === grantedWindow && currentReadiness === 'held' ? 'granted' : currentReadiness;
  const parts = [readinessLabels[readiness] ?? (readiness === 'granted' ? 'Granted' : readiness)];
  if (row.task_count) parts.push(`${row.task_count} ${row.task_count === 1 ? 'task' : 'tasks'}`);
  if (row.open_comments) parts.push(`${row.open_comments} open ${row.open_comments === 1 ? 'comment' : 'comments'}`);
  return parts.join(', ');
}

export const QUEUE_LABELS: Record<string, string> = { 'new-feature': 'New features', fixes: 'Fixes', friction: 'Friction', uncategorized: 'Uncategorized' };

export function groupPlans(plans: PlanListItem[]): PlanGroups {
  const groups: PlanGroups = { inProgress: [], queued: [], blocked: [], needsReview: [], done: [] };
  for (const plan of plans) {
    if (plan.status === 'in_progress') groups.inProgress.push(plan);
    else if (plan.status === 'queued') groups.queued.push(plan);
    else if (plan.status === 'blocked') groups.blocked.push(plan);
    else if (plan.status === 'needs_review') groups.needsReview.push(plan);
    else if (plan.status === 'done') groups.done.push(plan);
    else groups.needsReview.push(plan);
  }
  groups.queued.sort((a, b) => (a.queue_position ?? Number.MAX_SAFE_INTEGER) - (b.queue_position ?? Number.MAX_SAFE_INTEGER));
  return groups;
}
