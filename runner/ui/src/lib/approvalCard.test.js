import { describe, expect, it } from 'vitest';
import { approvalLabel, answerState } from './approvalCard.ts';
const agent = (agent_id, role = 'reviewer', workspace = '/tmp/repo') => ({ agent_id, role, workspace });
describe('approval cards', () => {
  it('uses role, workspace and short unique id', () => {
    expect(approvalLabel(agent('12345678-a'))).toBe('Reviewer: repo (12345678)');
    expect(approvalLabel(agent('abcdefgh-b'))).toBe('Reviewer: repo (abcdefgh)');
    expect(approvalLabel(agent('abcdefghi', 'builder', 'C:\\work\\app'))).toBe('Builder: app (abcdefgh)');
  });
  it('omits the workspace when the agent has none', () => {
    expect(approvalLabel(agent('2a197f8d-1', 'reviewer', null))).toBe('Reviewer (2a197f8d)');
    expect(approvalLabel(agent('2a197f8d-2', 'builder', ''))).toBe('Builder (2a197f8d)');
  });
  it('falls back to a plain agent role', () => {
    expect(approvalLabel(agent('abcdefgh-c', null, '/tmp/repo'))).toBe('Agent: repo (abcdefgh)');
  });
  it('shows title state', () => { expect(answerState('x', '', { x: 'allow' })).toBe('approved'); });
});
