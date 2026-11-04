import type { Agent } from './agentsApi';
import { isActionAgent } from './identitiesApi.ts';

export function stateTone(agent: Agent): 'running' | 'stalled' | 'danger' | 'neutral' {
  if (agent.lifecycle === 'failed') return 'danger';
  if (agent.lifecycle === 'rate_limited' || agent.idle_status === 'rate_limited') return 'stalled';
  if (agent.lifecycle === 'running') return 'running';
  return 'neutral';
}

export function actionItems(agents: Agent[]): Agent[] {
  return agents.filter(isActionAgent);
}
