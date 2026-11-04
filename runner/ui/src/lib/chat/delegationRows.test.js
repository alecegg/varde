import { describe, expect, it } from 'vitest';
import { delegationRows } from './delegationRows.ts';

const audit = (overrides = {}) => ({
  id: 1, phase: 'call', action: 'launch', status: 'allowed', agent_id: 'agent-1',
  plan_id: null, args_redacted: '{"role":"planner","prompt":"[12 chars]"}', ts: '2026-10-27T10:00:00Z',
  ...overrides,
});

describe('delegationRows', () => {
  it('renders readable launch targets without exposing redacted prompts', () => {
    expect(delegationRows([audit()])).toEqual([{ id: '1', text: 'Launched planner', ts: '2026-10-27T10:00:00Z' }]);
  });

  it('renders stop and archive actions using their target agent', () => {
    expect(delegationRows([
      audit({ id: 2, action: 'agent_stop', args_redacted: null, agent_id: 'agent-2' }),
      audit({ id: 3, action: 'agent_archive', args_redacted: null, agent_id: 'agent-3' }),
    ]).map(({ text }) => text)).toEqual(['Stopped agent-2', 'Archived agent-3']);
  });

  it('ignores denied and result records and unrelated actions', () => {
    expect(delegationRows([
      audit({ id: 2, status: 'denied' }),
      audit({ id: 3, phase: 'result' }),
      audit({ id: 4, action: 'agent_resume' }),
    ])).toEqual([]);
  });

  it('uses plan ids for plan-targeted launches', () => {
    expect(delegationRows([audit({ plan_id: 'plan-7' })])[0].text).toBe('Launched plan plan-7');
  });

  it('uses a readable manager chat launch line when audit arguments have no target', () => {
    expect(delegationRows([audit({ args_redacted: '{}', agent_id: null })], [
      { role: 'bot', text: 'I launched a builder for the parser work.', created_at: '2026-10-27T10:01:01Z' },
    ])[0].text).toBe('I launched a builder for the parser work.');
  });

  it('prefers the exact delegation copy when the audit includes a readable target', () => {
    expect(delegationRows([audit()], [
      { role: 'bot', text: 'Delegated to Builder: build the mobile chat shell.', created_at: '2026-10-27T10:01:01Z' },
    ])[0].text).toBe('Delegated to Builder: build the mobile chat shell.');
  });

  it('keeps the chat copy for a delegation audit row', () => {
    expect(delegationRows([audit({ args_redacted: '{}', agent_id: null })], [
      { role: 'bot', text: 'Delegated to Builder: build the mobile chat shell.', created_at: '2026-10-27T10:01:01Z' },
    ])[0].text).toBe('Delegated to Builder: build the mobile chat shell.');
  });
});
