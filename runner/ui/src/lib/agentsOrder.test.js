import { describe, expect, it } from 'vitest';
import { stableOrder } from './agentsOrder.ts';
const agent = (agent_id, pending_requests = []) => ({ agent_id, pending_requests, lifecycle: 'running' });
describe('stableOrder', () => {
  it('keeps existing order when priority changes', () => {
    expect(stableOrder([agent('second'), agent('first', [{ request_id: 'r' }])], ['first', 'second']).map((row) => row.agent_id)).toEqual(['first', 'second']);
  });
  it('appends new agents in attention order', () => {
    expect(stableOrder([agent('new'), agent('old')], ['old']).map((row) => row.agent_id)).toEqual(['old', 'new']);
  });
});
