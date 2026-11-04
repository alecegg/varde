export type MailSoakCriterion = {
  id: string;
  value: number | string | null;
  threshold: number | string;
  ok: boolean;
  n: number;
  insufficient: boolean;
};

export type MailSoakReport = {
  date: string;
  window_days: number;
  undeliverable: number;
  criteria: MailSoakCriterion[];
  active_orchestrators: number;
  all_ok: boolean;
  days_ok_streak: number;
};

export function criterionLabel(id: string): string {
  return ({
    'delivered-latency': 'Typical delivery time (95th percentile)',
    'ack-latency': 'Acknowledgement time (95th percentile)',
    'main-nudges': 'Main nudges',
    replays: 'Message replays',
    'status-clean': 'Message status',
    'send-no-mailman': 'Send without mailman',
    'merge-guard': 'Merge guard',
  } as Record<string, string>)[id] ?? id;
}

function seconds(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, '');
}

export function criterionValue(value: number | string | null, id: string): string {
  if (value === null) return '—';
  if (typeof value === 'string') return value;
  if (id === 'ack-latency' || id === 'delivered-latency') {
    if (value < 60) return `${seconds(value)} s`;
    const minutes = Math.floor(value / 60);
    const remainder = value % 60;
    return remainder === 0 ? `${minutes} min` : `${minutes} min ${seconds(remainder)} s`;
  }
  if (id === 'main-nudges') return `${value} ${value === 1 ? 'nudge' : 'nudges'}`;
  if (id === 'replays') return `${value} ${value === 1 ? 'replay' : 'replays'}`;
  if (id === 'status-clean') return value === 0 ? 'clean' : 'not clean';
  if (id === 'merge-guard') return value === 0 ? 'none overdue' : 'overdue';
  if (id === 'send-no-mailman') return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
  return String(value);
}

export function criterionPresentation(criterion: MailSoakCriterion) {
  const insufficient = criterion.insufficient;
  return {
    label: criterionLabel(criterion.id),
    measure: `Actual: ${criterionValue(criterion.value, criterion.id)} · Target: ${criterionValue(criterion.threshold, criterion.id)}`,
    status: insufficient ? 'Not enough data' : criterion.ok ? 'Pass' : 'Fail',
    tone: insufficient ? 'neutral' : criterion.ok ? 'pass' : 'fail',
    note: insufficient && criterion.n > 0 ? `Based on ${criterion.n} checks.` : '',
  } as const;
}

export function streakPresentation(report: Pick<MailSoakReport, 'all_ok' | 'days_ok_streak'>): string {
  const goal = 3;
  const passed = report.days_ok_streak >= goal;
  return `${passed ? 'Soak passed' : 'Soak in progress'} · ${report.days_ok_streak} of ${goal} passing days`;
}

export function requestStateForStatus(status: number): 'missing' | 'error' | 'ok' {
  if (status === 404) return 'missing';
  if (status < 200 || status >= 300) return 'error';
  return 'ok';
}

export function reportLoadMessage(state: 'missing' | 'error'): string {
  return state === 'missing'
    ? 'Mail soak report is not available yet.'
    : 'Could not load the mail soak report. Check your connection and retry.';
}
