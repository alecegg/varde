import type { Agent } from './agentsApi';

export type AgentStatusMarker = {
  tone: 'blocked' | 'running' | 'idle' | 'success';
  label: string;
  icon: string;
};

export function stateMarker(agent: Agent): AgentStatusMarker {
  if (agent.lifecycle === 'failed') return { tone: 'blocked', label: 'Failed', icon: '×' };
  if (agent.pending_requests.length || agent.idle_status?.startsWith('awaiting_')) {
    return { tone: 'blocked', label: 'Blocked', icon: '!' };
  }
  if (agent.lifecycle === 'running') return { tone: 'running', label: 'Running', icon: '▶' };
  if (agent.lifecycle === 'completed') return { tone: 'success', label: 'Completed', icon: '✓' };
  return { tone: 'idle', label: 'Idle', icon: '○' };
}
