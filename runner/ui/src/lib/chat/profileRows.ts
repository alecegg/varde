import { stateTone, type Identity } from '../identitiesApi.ts';

type ProfileRole = {
  harness?: string | null;
  model?: string | null;
  reasoning_effort?: string | null;
  mode?: string | null;
} | null | undefined;

export type ProfileRow = { label: 'Harness' | 'Model' | 'Limits' | 'Role'; value: string };
export type ProfileState = { label: string; tone: ReturnType<typeof stateTone> };

const NOT_SET = 'Not set';

function present(value: string | null | undefined): string {
  return value?.trim() || NOT_SET;
}

function friendlyHarness(value: string | null | undefined): string {
  const harness = value?.trim();
  if (!harness) return NOT_SET;
  if (harness.toLowerCase().startsWith('codex')) return 'Codex';
  return harness.split(/[-_\s]+/).map((word) => word[0].toUpperCase() + word.slice(1)).join(' ');
}

function limits(role: ProfileRole): string {
  const effort = role?.reasoning_effort?.trim();
  const mode = role?.mode?.trim();
  if (!effort && !mode) return NOT_SET;
  return [effort ? effort[0].toUpperCase() + effort.slice(1) : '', mode].filter(Boolean).join(', ');
}

function identityRole(identity: Identity | null | undefined): string {
  if (identity?.name?.trim()) return identity.name.trim();
  if (identity?.id === 'manager') return 'Manager';
  return NOT_SET;
}

export function profileRows(identity: Identity | null | undefined, role: ProfileRole): ProfileRow[] {
  return [
    { label: 'Harness', value: friendlyHarness(role?.harness) },
    { label: 'Model', value: present(role?.model) },
    { label: 'Limits', value: limits(role) },
    { label: 'Role', value: identityRole(identity) },
  ];
}

export function profileState(identity: Identity | null | undefined): ProfileState {
  const state = identity?.worst_state;
  return {
    label: state?.trim().toLowerCase().replace(/[\s_]+/g, '-') || 'idle',
    tone: stateTone(state),
  };
}

export function profileInitials(identity: Identity | null | undefined): string {
  const provided = identity?.initials?.trim();
  if (provided) return provided.toUpperCase();
  const fallback: Record<string, string> = {
    manager: 'MG', builder: 'BU', reviewer: 'RE', planner: 'PL', explorer: 'EX',
  };
  if (identity?.id && fallback[identity.id]) return fallback[identity.id];
  const name = identity?.name?.trim() || identity?.id || '?';
  const words = name.split(/\s+/).filter(Boolean);
  return words.length > 1
    ? words.slice(0, 2).map((word) => word[0]?.toUpperCase()).join('')
    : name.slice(0, 2).toUpperCase();
}

export function profileHue(identity: Identity | null | undefined): string {
  const hue = identity?.hue?.trim().toLowerCase();
  if (hue) return hue;
  const fallback: Record<string, string> = {
    manager: 'violet', builder: 'blue', reviewer: 'green', planner: 'orange', explorer: 'pink',
  };
  return fallback[identity?.id ?? ''] ?? 'violet';
}
