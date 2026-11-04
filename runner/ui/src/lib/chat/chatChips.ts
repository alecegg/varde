import type { HomeSummary } from '../homeList';

export type ChatChipDot = 'running' | 'queued' | 'needs-you' | null;
export type ChatChipHue = 'violet' | 'blue' | 'green' | 'orange' | 'pink';

export type ChatChip = {
  id: string;
  label: string;
  initials: string;
  hue: ChatChipHue;
  dot: ChatChipDot;
  needsYou: number;
  href: string;
  disabled?: boolean;
};

export type ManagerChip = {
  id: 'manager';
  label: 'Manager';
  threadKey: 'main';
  roleEnabled: boolean | null;
  state?: HomeSummary['state'];
  queued?: number;
  needs_you?: number;
};

const HUES: ChatChipHue[] = ['violet', 'blue', 'green', 'orange', 'pink'];
const PROTOTYPE_AGENTS: Record<string, { label: string; initials: string; hue: ChatChipHue }> = {
  manager: { label: 'Manager', initials: 'MG', hue: 'violet' },
  builder: { label: 'Builder', initials: 'BU', hue: 'blue' },
  reviewer: { label: 'Reviewer', initials: 'RE', hue: 'green' },
  planner: { label: 'Planner', initials: 'PL', hue: 'orange' },
  explorer: { label: 'Explorer', initials: 'EX', hue: 'pink' },
};

export function chatChips(summaries: HomeSummary[], manager: ManagerChip): ChatChip[] {
  const agents = summaries.filter(
    (summary) => summary.role !== 'manager-bot' && summary.role !== manager.id && summary.agent_id !== manager.id,
  );
  return [managerChip(manager), ...agents.map(summaryChip)];
}

export function needsYouTotal(chips: ChatChip[]): number {
  return chips.reduce((total, chip) => total + chip.needsYou, 0);
}

export function statusLine(chips: ChatChip[]): string {
  const running = chips.filter((chip) => chip.dot === 'running').length;
  const queued = chips.filter((chip) => chip.dot === 'queued').length;
  return `${running} running, ${queued} queued`;
}

function managerChip(manager: ManagerChip): ChatChip {
  const disabled = manager.roleEnabled === false;
  const agent = PROTOTYPE_AGENTS[manager.id];
  return {
    id: manager.id,
    label: agent?.label ?? manager.label,
    initials: agent?.initials ?? initials(manager.label),
    hue: agent?.hue ?? hueFor(manager.id),
    dot: disabled ? null : statusDot(manager),
    needsYou: manager.needs_you ?? 0,
    href: `/thread/${manager.id}`,
    ...(disabled ? { disabled: true } : {}),
  };
}

function summaryChip(summary: HomeSummary): ChatChip {
  const id = summary.agent_id || summary.role;
  const agent = PROTOTYPE_AGENTS[id];
  return {
    id,
    label: agent?.label ?? summary.role,
    initials: agent?.initials ?? initials(summary.role),
    hue: agent?.hue ?? hueFor(id),
    dot: statusDot(summary),
    needsYou: summary.needs_you,
    href: `/thread/${id}`,
  };
}

function statusDot(status: { state?: HomeSummary['state']; queued?: number; needs_you?: number }): ChatChipDot {
  if ((status.queued ?? 0) > 0) return 'queued';
  if (status.state === 'running') return 'running';
  if ((status.needs_you ?? 0) > 0 || status.state === 'needs_you') return 'needs-you';
  return null;
}

function initials(label: string): string {
  return label
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function hueFor(id: string): ChatChipHue {
  if (id === 'manager') return 'violet';
  let hash = 0;
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return HUES[hash % HUES.length];
}
