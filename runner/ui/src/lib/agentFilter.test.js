import { describe, expect, it } from 'vitest';
import { agentState, blockedFirst, filterAgents, filterToParams, parseFilter, stateCounts } from './agentFilter.ts';

const agent = (agent_id, lifecycle = 'running', extra = {}) => ({
  agent_id,
  role: 'worker',
  workspace: '/work/demo',
  lifecycle,
  idle_status: null,
  pending_requests: [],
  ...extra,
});

describe('agentState', () => {
  it('prioritizes pending requests and maps lifecycle states', () => {
    expect(agentState(agent('blocked', 'running', { pending_requests: [{}] }))).toBe('blocked');
    expect(agentState(agent('running'))).toBe('running');
    expect(agentState(agent('idle', 'idle'))).toBe('idle');
    expect(agentState(agent('done', 'completed'))).toBe('completed');
    expect(agentState(agent('failed', 'failed'))).toBe('failed');
  });
});

describe('filterAgents', () => {
  const agents = [agent('a1'), agent('b2', 'idle', { role: 'reviewer', workspace: '/work/other' })];

  it('filters state and searches role, workspace, and id without case sensitivity', () => {
    expect(filterAgents(agents, { state: 'idle', query: '' })).toEqual([agents[1]]);
    expect(filterAgents(agents, { state: 'all', query: 'REVIEW' })).toEqual([agents[1]]);
    expect(filterAgents(agents, { state: 'all', query: 'OTHER' })).toEqual([agents[1]]);
    expect(filterAgents(agents, { state: 'all', query: 'A1' })).toEqual([agents[0]]);
  });
});

describe('stateCounts and blockedFirst', () => {
  it('counts all states and puts blocked agents first stably', () => {
    const agents = [agent('run'), agent('wait', 'running', { pending_requests: [{}] }), agent('done', 'completed')];
    expect(stateCounts(agents)).toEqual({ all: 3, blocked: 1, running: 1, idle: 0, completed: 1, failed: 0 });
    expect(blockedFirst(agents).map(({ agent_id }) => agent_id)).toEqual(['wait', 'run', 'done']);
  });
});

describe('URL filter', () => {
  it('parses defaults and round trips non-default filter values', () => {
    expect(parseFilter(new URLSearchParams())).toEqual({ state: 'all', query: '' });
    const filter = { state: 'failed', query: 'reviewer' };
    expect(parseFilter(filterToParams(filter))).toEqual(filter);
  });
});
