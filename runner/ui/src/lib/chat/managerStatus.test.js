import { describe, expect, it } from 'vitest';
import { DISABLED_REASON, managerStatus } from './managerStatus.ts';

describe('managerStatus', () => {
  it('reports a running manager when the governor and chat both run', () => {
    expect(managerStatus({ chatState: 'running', governorState: 'running' })).toEqual({
      chip: 'running', label: 'Running', tone: 'running', reason: null, href: '/chat', composerDisabled: false
    });
  });

  it('keeps the composer usable while paused and carries the pause reason', () => {
    const status = managerStatus({ chatState: 'running', governorState: 'paused', reason: 'paused by user' });
    expect(status.chip).toBe('paused');
    expect(status.label).toBe('Paused');
    expect(status.reason).toBe('paused by user');
    expect(status.composerDisabled).toBe(false);
  });

  it('disables the composer and says why when the manager-bot role is off', () => {
    const status = managerStatus({ chatState: 'running', governorState: 'running', roleEnabled: false });
    expect(status.chip).toBe('off');
    expect(status.label).toBe('Off');
    expect(status.reason).toBe(DISABLED_REASON);
    expect(status.href).toBe('/settings');
    expect(status.composerDisabled).toBe(true);
  });

  it('explains when the configured harness cannot provide the manager chat', () => {
    const status = managerStatus({ chatState: 'unavailable', governorState: 'running' });
    expect(status.chip).toBe('unavailable');
    expect(status.label).toBe('Unavailable');
    expect(status.reason).toMatch(/claude-sdk cannot enforce the restricted profile/);
    expect(status.reason).toMatch(/Switch the manager to a supported harness in Settings/);
    expect(status.reason).not.toMatch(/Enable roles\.manager-bot/);
    expect(status.composerDisabled).toBe(true);
  });

  it('disables the composer for a killed manager', () => {
    const status = managerStatus({ chatState: 'running', governorState: 'killed' });
    expect(status.chip).toBe('killed');
    expect(status.label).toBe('Killed');
    expect(status.composerDisabled).toBe(true);
  });

  it('falls back to an unavailable status with a retry hint', () => {
    const status = managerStatus({});
    expect(status.chip).toBe('unavailable');
    expect(status.reason).toBe('Manager status is unavailable; retry in a moment');
    expect(status.href).toBeNull();
  });
});
