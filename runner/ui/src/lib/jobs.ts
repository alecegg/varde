import { formatDateTime } from './ui/date.ts';

export type JobRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  trigger: string;
  outcome: string;
  error: string | null;
  model_tokens: number | null;
  cost_usd: number | null;
};

export type Job = {
  key: string;
  title: string;
  enabled: boolean;
  spends_model_usage: boolean;
  run_budget_usd: number | null;
  run_budget_tokens: number | null;
  schedule_time: string;
  next_run_at: string | null;
  state: string;
  last_run: JobRun | null;
  warnings: unknown[];
  failures: unknown[];
  summary_error: string | null;
  budget_exhausted: boolean;
  coverage: { found: number; analyzed: number; skipped: number; failed: number; pending: number } | null;
  stop_reason: string | null;
};

export function orderJobs(jobs: Job[]): Job[] {
  return [...jobs].sort((a, b) => Number(isUrgent(b)) - Number(isUrgent(a)) || a.title.localeCompare(b.title));
}

function isUrgent(job: Job): boolean {
  return job.state === 'failed' || job.state === 'paused';
}

export function jobStateTone(state: string): 'blocked' | 'running' | 'success' | 'idle' {
  if (state === 'failed') return 'blocked';
  if (state === 'running') return 'running';
  if (state === 'succeeded') return 'success';
  return 'idle';
}

export function jobStatusLabel(state: string): 'running' | 'succeeded' | 'failed' | 'paused' | 'queued' | 'unknown' {
  if (state === 'running') return 'running';
  if (state === 'succeeded') return 'succeeded';
  if (state === 'failed') return 'failed';
  if (state === 'paused') return 'paused';
  if (state === 'queued') return 'queued';
  return 'unknown';
}

export function sweepSummary(warnings: number, failures: number): string {
  const warningLabel = warnings === 1 ? 'warning' : 'warnings';
  const failureLabel = failures === 1 ? 'failure' : 'failures';
  return `Sweep: ${warnings} ${warningLabel} · ${failures} session ${failureLabel}.`;
}

export function jobCardStatus(job: Job): { status: ReturnType<typeof jobStatusLabel>; label?: string } {
  if (job.key === 'sweep' && job.state === 'succeeded' && job.failures.length > 0) {
    const failureLabel = job.failures.length === 1 ? 'failure' : 'failures';
    return { status: 'succeeded', label: `Completed with ${job.failures.length} session ${failureLabel}` };
  }
  return { status: jobStatusLabel(job.state) };
}

export function lastRunStatusDiffers(job: Job): boolean {
  return Boolean(job.last_run && jobStatusLabel(job.state) !== jobStatusLabel(job.last_run.outcome));
}

export function displayDate(value: string | null | undefined): string {
  if (!value) return 'Not scheduled';
  return formatDateTime(value) ?? 'Not scheduled';
}

export function displayCost(value: number | null | undefined): string {
  return value == null ? 'Not reported' : `$${value.toFixed(4)}`;
}

export const JOB_POLL_MS = 3000;

export function anyJobRunning(jobs: Job[]): boolean {
  return jobs.some((job) => job.state === 'running');
}
