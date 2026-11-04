import { describe, expect, it } from 'vitest';
import { controlKind, initialDraft } from '../../lib/runnerConfigApi';
import { userSettings } from './userSettings.ts';

const item = (type, value) => ({ type, value });

describe('runner setting controls', () => {
  it('uses checkboxes for booleans and number inputs for integers', () => {
    expect(controlKind(item('boolean', false))).toBe('checkbox');
    expect(controlKind(item('integer', 600))).toBe('number');
  });

  it('initializes integer drafts as strings', () => {
    expect(initialDraft(item('integer', 600))).toBe('600');
    expect(initialDraft(item('boolean', false))).toBe(false);
  });

  it('keeps host-local runner controls in config only', () => {
    const items = [
      { key: 'runner.require_user_pairing' },
      { key: 'runner.idle_process_timeout_s' },
      { key: 'limits.max_live_instances' },
      { key: 'claude_cli.enabled' },
      { key: 'bot.sweep_interval_s', group: 'bot' },
    ];
    expect(userSettings(items).map(({ key }) => key)).toEqual([
      'limits.max_live_instances',
      'claude_cli.enabled',
    ]);
  });
});
