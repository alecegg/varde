import type { Agent } from './agentsApi';

export type AgentState = 'blocked' | 'running' | 'idle' | 'completed' | 'failed';
export type AgentFilterState = AgentState | 'all';
export type AgentFilter = { state: AgentFilterState; query: string };
export type AgentStateCounts = Record<AgentFilterState, number>;

const states = new Set<AgentFilterState>(['all', 'blocked', 'running', 'idle', 'completed', 'failed']);

export function agentState(agent: Agent): AgentState {
  if (agent.pending_requests.length > 0) return 'blocked';
  if (agent.lifecycle === 'running') return 'running';
  if (agent.lifecycle === 'completed' || agent.lifecycle === 'archived') return 'completed';
  if (agent.lifecycle === 'failed' || agent.lifecycle === 'rate_limited' || agent.idle_status === 'rate_limited') return 'failed';
  return 'idle';
}

export function filterAgents(agents: Agent[], filter: AgentFilter): Agent[] {
  const query = filter.query.trim().toLocaleLowerCase();
  return agents.filter((agent) => {
    if (filter.state !== 'all' && agentState(agent) !== filter.state) return false;
    if (!query) return true;
    return [agent.role, agent.workspace, agent.agent_id]
      .some((value) => value?.toLocaleLowerCase().includes(query));
  });
}

export function stateCounts(agents: Agent[]): AgentStateCounts {
  const counts: AgentStateCounts = { all: agents.length, blocked: 0, running: 0, idle: 0, completed: 0, failed: 0 };
  for (const agent of agents) counts[agentState(agent)] += 1;
  return counts;
}

export function blockedFirst(agents: Agent[]): Agent[] {
  return [...agents].sort((a, b) => Number(agentState(b) === 'blocked') - Number(agentState(a) === 'blocked'));
}

export function parseFilter(searchParams: URLSearchParams): AgentFilter {
  const requestedState = searchParams.get('state');
  return {
    state: requestedState && states.has(requestedState as AgentFilterState) ? requestedState as AgentFilterState : 'all',
    query: searchParams.get('q') ?? '',
  };
}

export function filterToParams(filter: AgentFilter): URLSearchParams {
  const params = new URLSearchParams();
  if (filter.state !== 'all') params.set('state', filter.state);
  if (filter.query) params.set('q', filter.query);
  return params;
}
