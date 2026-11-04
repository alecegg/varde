import { describe, expect, it } from 'vitest';
import { affectedText, rolesAffected } from './sdkRoles.ts';

describe('SDK roles summary', () => {
  it('lists roles whose type moves to the Claude SDK', () => {
    const diff = [{ key: 'types.standard.harness', before: 'claude-cli', after: 'claude-sdk' }];
    const roles = { planner: { type: 'standard' }, worker: { type: 'heavy' }, guard: { type: 'guard' } };
    expect(rolesAffected(diff, roles)).toEqual(['planner']);
    expect(affectedText(rolesAffected(diff, roles))).toBe('These roles will use Claude Code: planner');
  });

  it('explains when no role changes', () => {
    expect(affectedText([])).toBe('No roles need changes; this enables Claude Code for them.');
  });
});
