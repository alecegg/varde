export type ManagerChip = 'running' | 'paused' | 'killed' | 'unavailable' | 'off';
export type ManagerTone = 'running' | 'waiting' | 'blocked' | 'idle' | 'neutral';

export type ManagerStatus = {
  chip: ManagerChip;
  label: string;
  tone: ManagerTone;
  reason: string | null;
  href: string | null;
  composerDisabled: boolean;
};

export type ManagerInputs = {
  chatState?: string | null;
  governorState?: string | null;
  reason?: string | null;
  roleEnabled?: boolean;
};

export const DISABLED_REASON = 'Manager bot is off. Start it to chat.';
const KILLED_REASON = 'The manager bot was killed; restart it in Settings';
const UNKNOWN_REASON = 'Manager status is unavailable; retry in a moment';
const UNAVAILABLE_REASON = 'Manager chat is unavailable because claude-sdk cannot enforce the restricted profile. Switch the manager to a supported harness in Settings.';

const RUNNING: ManagerStatus = { chip: 'running', label: 'Running', tone: 'running', reason: null, href: '/chat', composerDisabled: false };
const PAUSED: ManagerStatus = { chip: 'paused', label: 'Paused', tone: 'waiting', reason: null, href: '/chat', composerDisabled: false };
const KILLED: ManagerStatus = { chip: 'killed', label: 'Killed', tone: 'blocked', reason: KILLED_REASON, href: '/settings', composerDisabled: true };
const DISABLED: ManagerStatus = { chip: 'off', label: 'Off', tone: 'idle', reason: DISABLED_REASON, href: '/settings', composerDisabled: true };
const UNAVAILABLE: ManagerStatus = { chip: 'unavailable', label: 'Unavailable', tone: 'blocked', reason: UNAVAILABLE_REASON, href: '/settings', composerDisabled: true };
const UNKNOWN: ManagerStatus = { chip: 'unavailable', label: 'Unavailable', tone: 'blocked', reason: UNKNOWN_REASON, href: null, composerDisabled: true };

/** Resolve the manager's run state and whether its composer is available. */
export function managerStatus({
  chatState = null,
  governorState = null,
  reason = null,
  roleEnabled = true
}: ManagerInputs = {}): ManagerStatus {
  if (!roleEnabled) return DISABLED;
  if (governorState === 'killed') return KILLED;
  if (governorState === 'paused' || chatState === 'paused') return { ...PAUSED, reason: reason ?? null };
  if (chatState === 'unavailable') return UNAVAILABLE;
  if (governorState === 'running' || chatState === 'running') return RUNNING;
  return { ...UNKNOWN, reason: reason ?? UNKNOWN_REASON };
}
