import { describe, expect, it } from 'vitest';
import { profileHue, profileInitials, profileRows, profileState } from './profileRows.ts';

const identity = {
  id: 'worker', name: 'Researcher', label: 'Researcher', description: 'Finds and summarizes sources',
  role: 'researcher', count: 1, worst_state: 'needs you', instances: null,
};

describe('profileRows', () => {
  it('shows harness, model, limits, and the identity role', () => {
    expect(profileRows(identity, {
      harness: 'codex-app-server', model: 'gpt-6.1', reasoning_effort: 'medium', mode: 'workspace-write',
    })).toEqual([
      { label: 'Harness', value: 'Codex' },
      { label: 'Model', value: 'gpt-6.1' },
      { label: 'Limits', value: 'Medium, workspace-write' },
      { label: 'Role', value: 'Researcher' },
    ]);
  });

  it('marks missing model fields as not set', () => {
    expect(profileRows(identity, { harness: 'pi', model: '', reasoning_effort: '', mode: '' })).toEqual([
      { label: 'Harness', value: 'Pi' },
      { label: 'Model', value: 'Not set' },
      { label: 'Limits', value: 'Not set' },
      { label: 'Role', value: 'Researcher' },
    ]);
  });

  it('uses a friendly manager role when identity details are absent', () => {
    expect(profileRows({ id: 'manager' }, { harness: '', model: 'manager-model', reasoning_effort: 'high', mode: 'read-only' })).toEqual([
      { label: 'Harness', value: 'Not set' },
      { label: 'Model', value: 'manager-model' },
      { label: 'Limits', value: 'High, read-only' },
      { label: 'Role', value: 'Manager' },
    ]);
  });

  it('uses the identity name as its role label', () => {
    expect(profileRows(identity, null)[3]).toEqual({ label: 'Role', value: 'Researcher' });
  });

  it('uses not set for unknown agents', () => {
    expect(profileRows({ id: 'unknown' }, null)[3]).toEqual({ label: 'Role', value: 'Not set' });
  });
});

describe('profileState', () => {
  it('returns the shared state label and tone for the profile pill', () => {
    expect(profileState(identity)).toEqual({ label: 'needs-you', tone: 'needs-input' });
    expect(profileState(null)).toEqual({ label: 'idle', tone: 'idle' });
  });
});

describe('profile avatar data', () => {
  it('uses provided initials and hue, with identity-name fallbacks', () => {
    expect(profileInitials({ id: 'builder', name: 'Builder', initials: 'bu' })).toBe('BU');
    expect(profileInitials({ id: 'manager', name: 'Manager' })).toBe('MG');
    expect(profileInitials({ id: 'builder', name: 'Builder', initials: 'BU' })).toBe('BU');
    expect(profileHue({ id: 'builder', name: 'Builder' })).toBe('blue');
    expect(profileHue({ id: 'custom', name: 'Custom', hue: 'pink' })).toBe('pink');
  });
});
