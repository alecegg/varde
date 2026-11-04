import { describe, expect, it } from 'vitest';
import { displayChoiceName, displayHarnessName } from './displayNames.ts';

describe('settings display names', () => {
  it('uses familiar names for native harnesses in every Settings selector', () => {
    expect(['claude-cli', 'Claude Cli', 'Pi-Rpc', 'Pi-Durable', 'Codex-App-Server', 'Opencode-Http'].map(displayHarnessName)).toEqual([
      'Claude Code (terminal)', 'Claude Code (terminal)', 'Pi (local)', 'Pi (persistent sessions)', 'Codex', 'OpenCode',
    ]);
  });

  it('capitalizes role type labels without changing their stored values', () => {
    expect(displayChoiceName('light')).toBe('Light');
    expect(displayChoiceName('review')).toBe('Review');
  });
});
