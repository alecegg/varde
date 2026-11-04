import type { Agent } from './agentsApi';

export function approvalLabel(agent: Agent): string {
  const role = agent.role ? `${agent.role[0].toUpperCase()}${agent.role.slice(1)}` : 'Agent';
  const workspace = agent.workspace?.split(/[\\/]/).filter(Boolean).at(-1);
  const shortId = `(${agent.agent_id.slice(0, 8)})`;
  return workspace ? `${role}: ${workspace} ${shortId}` : `${role} ${shortId}`;
}

export function answerState(key: string, answering: string, answered: Record<string, string>): 'idle' | 'sending' | 'approved' | 'denied' {
  if (answering === key) return 'sending';
  if (answered[key] === 'allow') return 'approved';
  if (answered[key] === 'deny') return 'denied';
  return 'idle';
}
